from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Dict
import pandas as pd


@dataclass
class Position:
    ticket: int
    symbol: str
    order_type: str
    volume: float
    open_price: float
    sl: float
    tp: float
    current_price: float
    profit: float
    magic: int = 123456
    comment: str = ""


class BrokerInterface(ABC):

    @abstractmethod
    def connect(self) -> bool:

        pass

    @abstractmethod
    def disconnect(self) -> None:

        pass

    @abstractmethod
    def get_balance_and_equity(self) -> tuple[float, float]:

        pass

    @abstractmethod
    def get_symbol_info(self, symbol: str) -> Optional[Dict]:

        pass

    @abstractmethod
    def get_candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:

        pass

    @abstractmethod
    def get_positions(self, symbol: str) -> List[Position]:

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

        pass

    @abstractmethod
    def modify_position(self, ticket: int, sl: float, tp: float) -> bool:

        pass

    @abstractmethod
    def close_position(self, ticket: int) -> bool:

        pass
