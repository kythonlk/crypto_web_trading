from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Dict
import pandas as pd


@dataclass
class Position:
    ticket: int
    symbol: str
    order_type: str  # "BUY" or "SELL"
    volume: float
    open_price: float
    sl: float
    tp: float
    current_price: float
    profit: float
    magic: int = 123456
    comment: str = ""


class BrokerInterface(ABC):
    """
    Abstract Broker Interface enabling interchangeable execution engines
    between live MetaTrader 5 and test/paper simulation environments.
    """

    @abstractmethod
    def connect(self) -> bool:
        """Initialize connection to the broker terminal or API."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection cleanly."""
        pass

    @abstractmethod
    def get_balance_and_equity(self) -> tuple[float, float]:
        """Returns (balance, equity)."""
        pass

    @abstractmethod
    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """
        Returns symbol specifications:
        {
            'ask': float,
            'bid': float,
            'spread': float,
            'point': float,
            'digits': int,
            'volume_min': float,
            'volume_step': float,
            'volume_max': float
        }
        """
        pass

    @abstractmethod
    def get_candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        """
        Returns OHLCV DataFrame with columns:
        ['time', 'open', 'high', 'low', 'close', 'volume']
        """
        pass

    @abstractmethod
    def get_positions(self, symbol: str) -> List[Position]:
        """Returns currently open positions for the given symbol."""
        pass

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        sl: float,
        tp: float,
        comment: str = "bot_trade",
    ) -> Optional[int]:
        """Places a market order. Returns ticket id on success, None on failure."""
        pass

    @abstractmethod
    def modify_position(self, ticket: int, sl: float, tp: float) -> bool:
        """Modifies Stop Loss and Take Profit of an existing position."""
        pass

    @abstractmethod
    def close_position(self, ticket: int) -> bool:
        """Closes an open position at current market price."""
        pass
