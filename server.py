import os
import sys
import time
import math
import logging
import threading
from functools import wraps
from typing import Dict, Any, List
import jwt
from flask import Flask, jsonify, request, send_from_directory

from config import config
from bot.broker_interface import BrokerInterface, Position
from bot.mt5_broker import MT5Broker, MT5_AVAILABLE
from bot.mock_broker import PublicApiMockBroker
from bot.risk_manager import RiskManager
from bot.strategy import TrendMomentumStrategy
from bot.regime_strategy import RegimeBreakoutStrategy
from bot.position_tracker import PositionTracker

if MT5_AVAILABLE:
    import MetaTrader5 as mt5
else:
    mt5 = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("DashboardServer")

app = Flask(__name__, static_folder=".")


class WebTradingEngine:
    def __init__(self):
        self.running = True
        self.paused = False
        self.last_bar = None
        self.latest_signal: Dict[str, Any] = {
            "action": "HOLD",
            "reason": "Initializing...",
            "rsi": 50.0,
            "atr": 0.0,
            "ema_fast": 0.0,
            "ema_slow": 0.0,
            "time": "",
        }
        self.equity_history: List[Dict[str, Any]] = []

        # Initialize broker
        if config.bot_mode == "MT5":
            logger.info("Initializing Live MetaTrader 5 Engine for Web Dashboard...")
            self.broker: BrokerInterface = MT5Broker(
                account=config.mt5_account,
                password=config.mt5_password,
                server=config.mt5_server,
                path=config.mt5_path,
            )
        else:
            logger.info(f"Initializing Public API Paper Broker (Symbol: {config.symbol})...")
            self.broker: BrokerInterface = PublicApiMockBroker(
                initial_balance=10000.0,
                symbol=config.symbol,
            )

        self.risk_manager = RiskManager(
            max_risk_per_trade_pct=config.max_risk_per_trade_pct,
            max_daily_drawdown_pct=config.max_daily_drawdown_pct,
            max_spread_points=config.max_spread_points,
            max_open_positions=config.max_open_positions,
        )

        self.strategy_name = config.strategy
        self._init_strategy()

        self.tracker = PositionTracker(
            broker=self.broker,
            breakeven_r_trigger=config.breakeven_r_trigger,
            trailing_stop_enabled=config.trailing_stop_enabled,
        )

    def _init_strategy(self):
        if self.strategy_name == "breakout":
            self.strategy = RegimeBreakoutStrategy(
                atr_multiplier_sl=config.atr_multiplier_sl,
                risk_reward_ratio=config.risk_reward_ratio,
            )
        else:
            self.strategy = TrendMomentumStrategy(
                atr_multiplier_sl=config.atr_multiplier_sl,
                risk_reward_ratio=config.risk_reward_ratio,
            )

    def start_background_loop(self):
        thread = threading.Thread(target=self._run_loop, daemon=True)
        thread.start()

    def _run_loop(self):
        logger.info("Starting WebTradingEngine trading loop...")
        if not self.broker.connect():
            logger.error("Failed to connect broker in background loop.")

        while self.running:
            try:
                if not self.paused and self.broker.connected:
                    self._iterate()
            except Exception as e:
                logger.exception(f"Error in engine iteration: {e}")

            time.sleep(max(1.0, config.poll_interval_seconds))

    def _iterate(self):
        balance, equity = self.broker.get_balance_and_equity()
        open_positions = self.broker.get_positions(config.symbol)
        sym_info = self.broker.get_symbol_info(config.symbol)

        # Record equity history point
        now_str = time.strftime("%H:%M:%S")
        if not self.equity_history or len(self.equity_history) == 0 or time.time() - self.equity_history[-1].get("timestamp", 0) >= 15:
            self.equity_history.append({
                "time": now_str,
                "timestamp": time.time(),
                "equity": round(equity, 2),
                "balance": round(balance, 2),
            })
            if len(self.equity_history) > 100:
                self.equity_history.pop(0)

        if not sym_info:
            return

        candles = self.broker.get_candles(config.symbol, config.timeframe, count=250)
        signal = self.strategy.evaluate(candles, config.symbol)

        # Update latest signal info for frontend
        indicators = {}
        if not candles.empty and len(candles) >= 30:
            ind_df = self.strategy.calculate_indicators(candles)
            if not ind_df.empty:
                last_row = ind_df.iloc[-1]
                indicators = {
                    "rsi": round(float(last_row.get("rsi", 50.0)), 2),
                    "ema_fast": round(float(last_row.get("ema_fast", 0.0)), 5),
                    "ema_slow": round(float(last_row.get("ema_slow", 0.0)), 5),
                    "atr": round(float(last_row.get("atr", 0.0)), 5),
                }

        self.latest_signal = {
            "action": signal.action,
            "symbol": config.symbol,
            "entry_price": signal.entry_price,
            "sl_price": signal.sl_price,
            "tp_price": signal.tp_price,
            "reason": signal.reason,
            "rsi": indicators.get("rsi", 50.0),
            "ema_fast": indicators.get("ema_fast", 0.0),
            "ema_slow": indicators.get("ema_slow", 0.0),
            "atr": indicators.get("atr", signal.atr),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        # Update trailing stops & breakeven
        self.tracker.update_positions(config.symbol, current_atr=signal.atr)

        # Prevent duplicate entries on same bar
        if candles.empty or candles.iloc[-1]["time"] == self.last_bar:
            return
        self.last_bar = candles.iloc[-1]["time"]

        if signal.action not in ["BUY", "SELL"]:
            return

        can_trade = self.risk_manager.can_open_new_trade(
            current_equity=equity,
            open_positions_count=len(open_positions),
            symbol_info=sym_info,
        )
        if not can_trade:
            return

        volume = self.risk_manager.calculate_position_size(
            equity=equity,
            entry_price=sym_info["ask"] if signal.action == "BUY" else sym_info["bid"],
            sl_price=signal.sl_price,
            symbol_info=sym_info,
        )
        if volume <= 0:
            return

        ticket = self.broker.place_order(
            symbol=config.symbol,
            order_type=signal.action,
            volume=volume,
            sl=signal.sl_price,
            tp=signal.tp_price,
            comment="algo_dashboard",
        )
        if ticket:
            self.tracker.register_position(ticket, signal.entry_price, signal.sl_price)


# Global Engine Instance
engine = WebTradingEngine()


# --- JWT Authentication Middleware ---

def create_jwt_token(username: str) -> str:
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + 86400 * 7,  # 7 days validity
    }
    return jwt.encode(payload, config.jwt_secret_key, algorithm="HS256")


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        elif "token" in request.args:
            token = request.args.get("token")

        if not token:
            return jsonify({"error": "Unauthorized: Authentication token missing", "authenticated": False}), 401

        try:
            payload = jwt.decode(token, config.jwt_secret_key, algorithms=["HS256"])
            request.user = payload["sub"]
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Unauthorized: Token has expired", "authenticated": False}), 401
        except Exception:
            return jsonify({"error": "Unauthorized: Invalid token", "authenticated": False}), 401

        return f(*args, **kwargs)
    return decorated


# --- Static and Auth Endpoints ---

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(force=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()

    if username == config.dashboard_username and password == config.dashboard_password:
        token = create_jwt_token(username)
        logger.info(f"User '{username}' logged in successfully via JWT.")
        return jsonify({
            "success": True,
            "token": token,
            "username": username,
            "expires_in": 86400 * 7,
        })

    logger.warning(f"Failed login attempt for username: {username}")
    return jsonify({"success": False, "error": "Invalid username or password"}), 401


@app.route("/api/auth/me", methods=["GET"])
@require_auth
def auth_me():
    return jsonify({
        "authenticated": True,
        "username": getattr(request, "user", "admin"),
    })


# --- Protected REST API Endpoints ---

@app.route("/api/status", methods=["GET"])
@require_auth
def get_status():
    balance, equity = engine.broker.get_balance_and_equity()
    open_positions = engine.broker.get_positions("")

    account_data = {
        "login": config.mt5_account,
        "server": config.mt5_server,
        "trade_mode": "DEMO",
        "currency": "USD",
        "balance": balance,
        "equity": equity,
        "margin": 0.0,
        "free_margin": equity,
        "profit": round(equity - balance, 2),
    }

    algo_trading_allowed = True
    if config.bot_mode == "MT5" and MT5_AVAILABLE:
        try:
            info = mt5.account_info()
            term = mt5.terminal_info()
            if info:
                account_data["login"] = info.login
                account_data["server"] = info.server
                account_data["currency"] = info.currency
                account_data["balance"] = float(info.balance)
                account_data["equity"] = float(info.equity)
                account_data["margin"] = float(info.margin)
                account_data["free_margin"] = float(info.margin_free)
                account_data["profit"] = float(info.profit)
                account_data["trade_mode"] = "DEMO" if info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "REAL"
            if term:
                algo_trading_allowed = bool(term.trade_allowed)
        except Exception:
            pass

    # Today's PnL calculation
    base_equity = engine.risk_manager.starting_day_equity or balance or 100000.0
    today_pnl = round(equity - base_equity, 2)
    today_pnl_pct = round((today_pnl / base_equity) * 100.0, 2) if base_equity > 0 else 0.0

    # Drawdown calculation
    drawdown_pct = 0.0
    if base_equity > 0 and equity < base_equity:
        drawdown_pct = round(((base_equity - equity) / base_equity) * 100.0, 2)

    return jsonify({
        "connected": engine.broker.connected,
        "bot_mode": config.bot_mode,
        "is_paused": engine.paused,
        "algo_trading_allowed": algo_trading_allowed,
        "account": account_data,
        "today_pnl": today_pnl,
        "today_pnl_pct": today_pnl_pct,
        "drawdown_pct": drawdown_pct,
        "symbol": config.symbol,
        "timeframe": config.timeframe,
        "strategy": engine.strategy_name,
        "open_positions_count": len(open_positions),
        "latest_signal": engine.latest_signal,
        "risk_settings": {
            "max_risk_per_trade_pct": engine.risk_manager.max_risk_pct,
            "max_daily_drawdown_pct": engine.risk_manager.max_daily_drawdown_pct,
            "max_open_positions": engine.risk_manager.max_open_positions,
            "max_spread_points": engine.risk_manager.max_spread_points,
            "breakeven_r_trigger": engine.tracker.breakeven_r,
            "trailing_stop_enabled": engine.tracker.trailing_enabled,
        },
    })


@app.route("/api/positions", methods=["GET"])
@require_auth
def get_positions():
    try:
        positions = engine.broker.get_positions("")
        result = []
        for p in positions:
            profit_val = float(p.profit) if p.profit is not None else 0.0
            sl_val = float(p.sl) if p.sl is not None else 0.0
            tp_val = float(p.tp) if p.tp is not None else 0.0
            open_val = float(p.open_price) if p.open_price is not None else 0.0
            curr_val = float(p.current_price) if p.current_price is not None else open_val
            result.append({
                "ticket": int(p.ticket),
                "symbol": str(p.symbol),
                "order_type": str(p.order_type),
                "volume": float(p.volume),
                "open_price": round(open_val, 5),
                "current_price": round(curr_val, 5),
                "sl": round(sl_val, 5),
                "tp": round(tp_val, 5),
                "profit": round(profit_val, 2),
                "comment": str(p.comment),
            })
        return jsonify(result)
    except Exception as e:
        logger.exception(f"Error in /api/positions: {e}")
        return jsonify([])


@app.route("/api/markets", methods=["GET"])
@require_auth
def get_markets():
    """Fetch live quotes for key Forex and Crypto pairs."""
    symbols = [
        {"id": "EURUSD", "name": "Euro / US Dollar", "type": "forex", "icon": "€", "color": "#7dd3fc"},
        {"id": "GBPUSD", "name": "British Pound / USD", "type": "forex", "icon": "£", "color": "#c4b5fd"},
        {"id": "BTCUSD", "name": "Bitcoin", "type": "crypto", "icon": "₿", "color": "#f5ac56"},
        {"id": "ETHUSD", "name": "Ethereum", "type": "crypto", "icon": "Ξ", "color": "#a5b4fc"},
    ]

    markets_data = []
    for item in symbols:
        sym = item["id"]
        ask, bid, spread = 0.0, 0.0, 0.0

        if config.bot_mode == "MT5" and MT5_AVAILABLE:
            try:
                s = mt5.symbol_info(sym) or mt5.symbol_info(sym + "T") or mt5.symbol_info(sym + ".m")
                if s:
                    ask = float(s.ask)
                    bid = float(s.bid)
                    spread = float(s.spread)
            except Exception:
                pass

        if ask == 0.0:
            if "BTC" in sym:
                ask, bid = 85850.0, 85845.0
            elif "ETH" in sym:
                ask, bid = 3450.0, 3448.0
            elif "EUR" in sym:
                ask, bid = 1.14150, 1.14140
            elif "GBP" in sym:
                ask, bid = 1.28250, 1.28240

        price_str = f"{ask:,.5f}" if ask < 10 else f"{ask:,.2f}"
        markets_data.append({
            "symbol": sym,
            "name": item["name"],
            "category": item["type"],
            "icon": item["icon"],
            "color": item["color"],
            "ask": ask,
            "bid": bid,
            "price": price_str,
            "spread": spread,
            "change_24h": "+0.45%" if "EUR" in sym else ("-0.12%" if "GBP" in sym else "+2.15%"),
        })

    return jsonify(markets_data)


@app.route("/api/chart", methods=["GET"])
@require_auth
def get_chart_data():
    period = request.args.get("period", "LIVE")
    return jsonify({
        "equity_history": engine.equity_history,
        "symbol": config.symbol,
        "period": period,
    })


@app.route("/api/bot/toggle", methods=["POST"])
@require_auth
def toggle_bot():
    engine.paused = not engine.paused
    state_str = "PAUSED" if engine.paused else "RUNNING"
    logger.info(f"Trading Bot state toggled: {state_str}")
    return jsonify({"success": True, "is_paused": engine.paused, "state": state_str})


@app.route("/api/settings", methods=["POST"])
@require_auth
def update_settings():
    data = request.get_json(force=True) or {}
    try:
        if "risk" in data:
            new_risk = float(data["risk"])
            engine.risk_manager.max_risk_pct = max(0.1, min(new_risk, 5.0))
        if "limit" in data:
            new_limit = float(data["limit"])
            engine.risk_manager.max_daily_drawdown_pct = max(0.5, min(new_limit, 10.0))
        if "strategy" in data:
            strat = str(data["strategy"]).lower()
            if strat in ["trend", "breakout"]:
                engine.strategy_name = strat
                engine._init_strategy()

        logger.info(f"Updated live settings: Risk={engine.risk_manager.max_risk_pct}%, Limit={engine.risk_manager.max_daily_drawdown_pct}%, Strategy={engine.strategy_name}")
        return jsonify({
            "success": True,
            "risk": engine.risk_manager.max_risk_pct,
            "limit": engine.risk_manager.max_daily_drawdown_pct,
            "strategy": engine.strategy_name,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/positions/close", methods=["POST"])
@require_auth
def close_position_route():
    data = request.get_json(force=True) or {}
    ticket = data.get("ticket")
    if not ticket:
        return jsonify({"success": False, "error": "Missing ticket"}), 400

    success = engine.broker.close_position(int(ticket))
    return jsonify({"success": success, "ticket": ticket})


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(".", path)


if __name__ == "__main__":
    engine.start_background_loop()
    logger.info("Starting Web Dashboard on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
