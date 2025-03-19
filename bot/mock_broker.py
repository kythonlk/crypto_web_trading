import logging
import time
import requests
from typing import Optional, List, Dict
import pandas as pd
import numpy as np
from .broker_interface import BrokerInterface, Position

logger = logging.getLogger("MockBroker")


class PublicApiMockBroker(BrokerInterface):
    """
    Simulation / Paper-trading broker using public market data API (e.g., Binance public API)
    or high-fidelity synthetic market generation.
    Supports real-time SL/TP trigger simulation, equity updates, and zero risk testing.
    """

    def __init__(self, initial_balance: float = 10000.0, symbol: str = "BTCUSDT"):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance
        self.symbol = symbol
        self.connected = False
        self.positions: Dict[int, Position] = {}
        self.next_ticket = 10001
        self.last_price = 60000.0
        self.spread_points = 10.0

    def connect(self) -> bool:
        self.connected = True
        logger.info(f"Connected to Public API Mock Broker. Starting Paper Balance: ${self.balance:,.2f}")
        # Test connection with a public ticker probe
        try:
            self._fetch_live_ticker(self.symbol)
        except Exception as e:
            logger.warning(f"Could not reach public ticker immediately ({e}), using default price feed.")
        return True

    def disconnect(self) -> None:
        self.connected = False
        logger.info("Public API Mock Broker disconnected.")

    def _fetch_live_ticker(self, symbol: str) -> float:
        """Fetch live ticker price from Binance public API with fallback."""
        try:
            clean_sym = symbol.replace("/", "").replace("_", "").upper()
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={clean_sym}"
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                self.last_price = float(resp.json()["price"])
                return self.last_price
        except Exception:
            pass
        return self.last_price

    def get_balance_and_equity(self) -> tuple[float, float]:
        self._update_open_positions()
        return self.balance, self.equity

    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        price = self._fetch_live_ticker(symbol)
        spread = self.spread_points * 0.1
        return {
            "ask": price + (spread / 2.0),
            "bid": price - (spread / 2.0),
            "spread": self.spread_points,
            "point": 0.01 if price > 100 else 0.0001,
            "digits": 2 if price > 100 else 5,
            "volume_min": 0.01,
            "volume_step": 0.01,
            "volume_max": 100.0,
        }

    def get_candles(self, symbol: str, timeframe: str, count: int = 100) -> pd.DataFrame:
        """
        Fetch OHLCV candles from public API. Falls back to synthetic candles
        if network is unavailable.
        """
        clean_sym = symbol.replace("/", "").replace("_", "").upper()
        # Map timeframe to Binance interval
        interval_map = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h", "H4": "4h", "D1": "1d"}
        interval = interval_map.get(timeframe.upper(), "15m")

        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={clean_sym}&interval={interval}&limit={min(count, 500)}"
            resp = requests.get(url, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                rows = []
                for item in data:
                    rows.append({
                        "time": pd.to_datetime(item[0], unit="ms"),
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "volume": float(item[5]),
                    })
                df = pd.DataFrame(rows)
                if not df.empty:
                    self.last_price = df.iloc[-1]["close"]
                    return df
        except Exception as e:
            logger.warning(f"Public API kline fetch failed ({e}). Generating realistic synthetic candles.")

        # Synthetic candle fallback for reliable offline testing
        now = pd.Timestamp.now()
        timestamps = [now - pd.Timedelta(minutes=15 * (count - i)) for i in range(count)]
        np.random.seed(42)
        returns = np.random.normal(0.0002, 0.003, count)
        prices = self.last_price * np.cumprod(1 + returns)

        opens = prices
        highs = opens * (1 + np.abs(np.random.normal(0, 0.002, count)))
        lows = opens * (1 - np.abs(np.random.normal(0, 0.002, count)))
        closes = opens * (1 + np.random.normal(0, 0.0015, count))
        volumes = np.random.uniform(50, 500, count)

        df = pd.DataFrame({
            "time": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        })
        self.last_price = float(df.iloc[-1]["close"])
        return df

    def _update_open_positions(self):
        """Update unrealized PnL and trigger SL/TP hits."""
        price = self._fetch_live_ticker(self.symbol)
        closed_tickets = []
        unrealized_total = 0.0

        for ticket, pos in list(self.positions.items()):
            pos.current_price = price
            if pos.order_type == "BUY":
                # Check Stop Loss
                if pos.sl > 0 and price <= pos.sl:
                    logger.info(f"[SL HIT] Position #{ticket} BUY closed at SL: {pos.sl:.2f}")
                    closed_tickets.append((ticket, pos.sl))
                    continue
                # Check Take Profit
                if pos.tp > 0 and price >= pos.tp:
                    logger.info(f"[TP HIT] Position #{ticket} BUY closed at TP: {pos.tp:.2f}")
                    closed_tickets.append((ticket, pos.tp))
                    continue
                pnl = (price - pos.open_price) * pos.volume
            else:  # SELL
                if pos.sl > 0 and price >= pos.sl:
                    logger.info(f"[SL HIT] Position #{ticket} SELL closed at SL: {pos.sl:.2f}")
                    closed_tickets.append((ticket, pos.sl))
                    continue
                if pos.tp > 0 and price <= pos.tp:
                    logger.info(f"[TP HIT] Position #{ticket} SELL closed at TP: {pos.tp:.2f}")
                    closed_tickets.append((ticket, pos.tp))
                    continue
                pnl = (pos.open_price - price) * pos.volume

            pos.profit = round(pnl, 2)
            unrealized_total += pos.profit

        for ticket, exit_price in closed_tickets:
            self._close_position_internal(ticket, exit_price)

        self.equity = round(self.balance + unrealized_total, 2)

    def _close_position_internal(self, ticket: int, exit_price: float):
        pos = self.positions.pop(ticket, None)
        if not pos:
            return
        if pos.order_type == "BUY":
            pnl = (exit_price - pos.open_price) * pos.volume
        else:
            pnl = (pos.open_price - exit_price) * pos.volume
        self.balance += pnl
        logger.info(f"Position #{ticket} closed at {exit_price:.2f}. Realized PnL: ${pnl:+,.2f} | Balance: ${self.balance:,.2f}")

    def get_positions(self, symbol: str) -> List[Position]:
        self._update_open_positions()
        return [p for p in self.positions.values() if p.symbol == symbol]

    def place_order(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        sl: float,
        tp: float,
        comment: str = "bot_trade",
    ) -> Optional[int]:
        info = self.get_symbol_info(symbol)
        if not info:
            return None

        price = info["ask"] if order_type.upper() == "BUY" else info["bid"]
        ticket = self.next_ticket
        self.next_ticket += 1

        pos = Position(
            ticket=ticket,
            symbol=symbol,
            order_type=order_type.upper(),
            volume=round(volume, 2),
            open_price=price,
            sl=sl,
            tp=tp,
            current_price=price,
            profit=0.0,
            comment=comment,
        )
        self.positions[ticket] = pos
        logger.info(
            f"[PAPER ORDER] #{ticket} {order_type} {volume:.2f} {symbol} @ {price:.2f} "
            f"(SL: {sl:.2f}, TP: {tp:.2f})"
        )
        self._update_open_positions()
        return ticket

    def modify_position(self, ticket: int, sl: float, tp: float) -> bool:
        if ticket in self.positions:
            pos = self.positions[ticket]
            pos.sl = sl
            pos.tp = tp
            logger.info(f"[PAPER MODIFY] #{ticket} updated SL -> {sl:.2f}, TP -> {tp:.2f}")
            return True
        return False

    def close_position(self, ticket: int) -> bool:
        if ticket in self.positions:
            info = self.get_symbol_info(self.positions[ticket].symbol)
            exit_price = info["bid"] if self.positions[ticket].order_type == "BUY" else info["ask"]
            self._close_position_internal(ticket, exit_price)
            return True
        return False
