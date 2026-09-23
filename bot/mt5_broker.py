import logging
import math
from typing import Optional, List, Dict
import pandas as pd
from .broker_interface import BrokerInterface, Position

logger = logging.getLogger("MT5Broker")

try:
    import MetaTrader5 as mt5

    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False


TIMEFRAME_MAP = {}
if MT5_AVAILABLE:
    TIMEFRAME_MAP = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }


class MT5Broker(BrokerInterface):

    def __init__(
        self,
        account: int = 0,
        password: str = "",
        server: str = "",
        path: str = "",
        magic_number: int = 998877,
    ):
        self.account = account
        self.password = password
        self.server = server
        self.path = path
        self.magic_number = magic_number
        self.connected = False

    def connect(self) -> bool:
        if not MT5_AVAILABLE:
            logger.error(
                "MetaTrader5 python package is not installed. Run 'pip install MetaTrader5'."
            )
            return False

        init_kwargs = {}
        if self.path:
            init_kwargs["path"] = self.path
        if self.account and self.password and self.server:
            init_kwargs["login"] = self.account
            init_kwargs["password"] = self.password
            init_kwargs["server"] = self.server

        if not mt5.initialize(**init_kwargs):
            logger.error(f"MT5 initialize failed: {mt5 .last_error ()}")
            return False

        account_info = mt5.account_info()
        if account_info is None:
            logger.error(f"Failed to fetch MT5 account info: {mt5 .last_error ()}")
            return False

        # Real account? Hard pass.
        if (
            not self.account
            or account_info.login != self.account
            or account_info.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO
        ):
            logger.error("Only the explicitly configured DEMO account is permitted.")
            mt5.shutdown()
            return False

        logger.info(
            f"Connected to MT5 - Account: {account_info .login }, "
            f"Server: {account_info .server }, Currency: {account_info .currency }, "
            f"Balance: {account_info .balance :.2f}"
        )
        self.connected = True
        return True

    def demo_trade_allowed(self):
        info = mt5.account_info()
        terminal = mt5.terminal_info()
        return bool(
            info
            and terminal
            and info.login == self.account
            and info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
            and info.trade_allowed
            and info.trade_expert
            and terminal.trade_allowed
            and not terminal.tradeapi_disabled
        )

    def disconnect(self) -> None:
        if MT5_AVAILABLE and self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("MT5 connection closed.")

    def get_balance_and_equity(self) -> tuple[float, float]:
        if not self.connected or not MT5_AVAILABLE:
            return 0.0, 0.0
        info = mt5.account_info()
        if info:
            return float(info.balance), float(info.equity)
        return 0.0, 0.0

    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        if not self.connected or not MT5_AVAILABLE:
            return None

        if not mt5.symbol_select(symbol, True):
            logger.warning(f"Failed to select symbol {symbol } in MT5 Market Watch.")

        s = mt5.symbol_info(symbol)
        if s is None:
            logger.error(f"Symbol {symbol } not found in MT5.")
            return None

        return {
            "ask": s.ask,
            "bid": s.bid,
            "spread": float(s.spread),
            "point": s.point,
            "digits": s.digits,
            "volume_min": s.volume_min,
            "volume_step": s.volume_step,
            "volume_max": s.volume_max,
            "trade_tick_size": s.trade_tick_size,
            "trade_tick_value_loss": s.trade_tick_value_loss,
        }

    def get_candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        if not self.connected or not MT5_AVAILABLE:
            return pd.DataFrame()

        tf = TIMEFRAME_MAP.get(timeframe.upper(), mt5.TIMEFRAME_M15)
        rates = mt5.copy_rates_from_pos(symbol, tf, 1, count)
        if rates is None or len(rates) == 0:
            logger.error(f"Failed to copy rates for {symbol }: {mt5 .last_error ()}")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df[["time", "open", "high", "low", "close", "tick_volume"]].rename(
            columns={"tick_volume": "volume"}
        )

    def get_positions(self, symbol: str) -> List[Position]:
        if not self.connected or not MT5_AVAILABLE:
            return []

        mt5_positions = mt5.positions_get(symbol=symbol)
        if mt5_positions is None:
            raise RuntimeError(
                "Unable to read positions; refusing to assume zero exposure"
            )

        result = []
        for p in mt5_positions:
            if p.magic == self.magic_number:
                order_type = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
                result.append(
                    Position(
                        ticket=p.ticket,
                        symbol=p.symbol,
                        order_type=order_type,
                        volume=p.volume,
                        open_price=p.price_open,
                        sl=p.sl,
                        tp=p.tp,
                        current_price=p.price_current,
                        profit=p.profit,
                        magic=p.magic,
                        comment=p.comment,
                    )
                )
        return result

    def _get_filling_type(self, symbol: str) -> int:
        sym = mt5.symbol_info(symbol)
        if sym is None:
            return mt5.ORDER_FILLING_IOC

        filling_mode = sym.filling_mode
        if filling_mode & mt5.SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        elif filling_mode & mt5.SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def place_order(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        sl: float,
        tp: float,
        comment: str = "bot_trade",
    ) -> Optional[int]:
        if not self.connected or not MT5_AVAILABLE:
            return None

        if not self.demo_trade_allowed() or order_type.upper() not in ("BUY", "SELL"):
            return None

        sym_info = self.get_symbol_info(symbol)
        if not sym_info:
            return None

        step = sym_info["volume_step"]
        if not math.isfinite(volume) or step <= 0:
            return None
        volume = round(
            math.floor(min(volume, sym_info["volume_max"]) / step + 1e-9) * step, 8
        )
        if volume < sym_info["volume_min"]:
            return None

        digits = sym_info["digits"]
        sl = round(sl, digits)
        tp = round(tp, digits)

        if order_type.upper() == "BUY":
            trade_type = mt5.ORDER_TYPE_BUY
            price = sym_info["ask"]
        else:
            trade_type = mt5.ORDER_TYPE_SELL
            price = sym_info["bid"]

        filling = self._get_filling_type(symbol)

        if not all(math.isfinite(x) and x > 0 for x in (price, sl, tp)):
            return None
        if not (sl < price < tp if order_type.upper() == "BUY" else tp < price < sl):
            return None

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": trade_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": self.magic_number,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        check = mt5.order_check(request)
        if check is None or check.retcode != 0:
            logger.error("Broker rejected order preflight")
            return None
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else mt5.last_error()
            logger.error(
                f"Order send failed ({order_type } {volume } {symbol }): {err }"
            )
            return None

        logger.info(
            f"Order placed successfully: Ticket #{result .order } ({order_type } @ {price :.{digits }f})"
        )
        return result.order

    def modify_position(self, ticket: int, sl: float, tp: float) -> bool:
        if not self.connected or not MT5_AVAILABLE:
            return False
        if not self.demo_trade_allowed():
            return False

        position = None
        for p in mt5.positions_get() or ():
            if p.ticket == ticket and p.magic == self.magic_number:
                position = p
                break

        if position is None:
            logger.warning(f"Cannot modify: Position #{ticket } not found.")
            return False

        sym_info = self.get_symbol_info(position.symbol)
        digits = sym_info["digits"] if sym_info else 5

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": position.symbol,
            "sl": round(sl, digits),
            "tp": round(tp, digits),
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(
                f"Position #{ticket } SL/TP updated: SL={sl :.{digits }f}, TP={tp :.{digits }f}"
            )
            return True

        err = result.comment if result else mt5.last_error()
        logger.error(f"Failed to modify position #{ticket }: {err }")
        return False

    def close_position(self, ticket: int) -> bool:
        if not self.connected or not MT5_AVAILABLE:
            return False
        if not self.demo_trade_allowed():
            return False

        pos = None
        for p in mt5.positions_get() or ():
            if p.ticket == ticket and p.magic == self.magic_number:
                pos = p
                break

        if pos is None:
            logger.warning(f"Cannot close: Position #{ticket } not found.")
            return False

        close_type = (
            mt5.ORDER_TYPE_SELL
            if pos.type == mt5.ORDER_TYPE_BUY
            else mt5.ORDER_TYPE_BUY
        )
        sym_info = self.get_symbol_info(pos.symbol)
        price = (
            sym_info["bid"] if close_type == mt5.ORDER_TYPE_SELL else sym_info["ask"]
        )
        filling = self._get_filling_type(pos.symbol)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "price": price,
            "deviation": 20,
            "magic": self.magic_number,
            "comment": "bot_close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Position #{ticket } closed at {price }")
            return True

        logger.error(
            f"Failed to close position #{ticket }: {result .comment if result else mt5 .last_error ()}"
        )
        return False
