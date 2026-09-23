import logging
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np
from config import config

logger = logging.getLogger("Strategy")


@dataclass
class TradeSignal:
    action: str
    symbol: str
    entry_price: float
    sl_price: float
    tp_price: float
    atr: float
    reason: str


class TrendMomentumStrategy:

    def __init__(
        self,
        fast_ema: int = 50,
        slow_ema: int = 200,
        rsi_period: int = 14,
        atr_period: int = 14,
        atr_multiplier_sl: float = config.atr_multiplier_sl,
        risk_reward_ratio: float = config.risk_reward_ratio,
    ):
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier_sl
        self.rr_ratio = risk_reward_ratio

    @staticmethod
    def calculate_indicators(
        df: pd.DataFrame,
        fast_ema: int = 50,
        slow_ema: int = 200,
        rsi_period: int = 14,
        atr_period: int = 14,
    ) -> pd.DataFrame:

        data = df.copy()

        data["ema_fast"] = data["close"].ewm(span=fast_ema, adjust=False).mean()
        data["ema_slow"] = data["close"].ewm(span=slow_ema, adjust=False).mean()

        delta = data["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
        rs = gain / (loss + 1e-10)
        data["rsi"] = 100 - (100 / (1 + rs))

        high_low = data["high"] - data["low"]
        high_close = (data["high"] - data["close"].shift()).abs()
        low_close = (data["low"] - data["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        data["atr"] = tr.rolling(window=atr_period).mean()

        return data

    def evaluate(self, df: pd.DataFrame, symbol: str) -> TradeSignal:

        hold_signal = TradeSignal(
            action="HOLD",
            symbol=symbol,
            entry_price=0.0,
            sl_price=0.0,
            tp_price=0.0,
            atr=0.0,
            reason="Insufficient data or no setup",
        )

        if df is None or len(df) < max(
            self.slow_ema, self.atr_period + 1, self.rsi_period + 1
        ):
            return hold_signal

        data = self.calculate_indicators(
            df, self.fast_ema, self.slow_ema, self.rsi_period, self.atr_period
        )
        last_row = data.iloc[-1]
        prev_row = data.iloc[-2]

        close = float(last_row["close"])
        ema_f = float(last_row["ema_fast"])
        ema_s = float(last_row["ema_slow"])
        rsi = float(last_row["rsi"])
        atr = float(last_row["atr"])

        if not all(np.isfinite(x) for x in (close, ema_f, ema_s, rsi, atr)) or atr <= 0:
            return hold_signal

        sl_distance = atr * self.atr_multiplier
        tp_distance = sl_distance * self.rr_ratio

        if (
            close > ema_f
            and ema_f > ema_s
            and 45.0 <= rsi <= 68.0
            and prev_row["close"] <= last_row["close"]
        ):
            sl = close - sl_distance
            tp = close + tp_distance
            logger.info(
                f"[BUY SIGNAL] {symbol } @ {close :.2f} | EMA50: {ema_f :.2f} > EMA200: {ema_s :.2f} | "
                f"RSI: {rsi :.1f} | SL: {sl :.2f} | TP: {tp :.2f} (1:{self .rr_ratio } R:R)"
            )
            return TradeSignal(
                action="BUY",
                symbol=symbol,
                entry_price=close,
                sl_price=sl,
                tp_price=tp,
                atr=atr,
                reason="Bullish EMA trend alignment with favorable RSI momentum",
            )

        if (
            close < ema_f
            and ema_f < ema_s
            and 32.0 <= rsi <= 55.0
            and prev_row["close"] >= last_row["close"]
        ):
            sl = close + sl_distance
            tp = close - tp_distance
            logger.info(
                f"[SELL SIGNAL] {symbol } @ {close :.2f} | EMA50: {ema_f :.2f} < EMA200: {ema_s :.2f} | "
                f"RSI: {rsi :.1f} | SL: {sl :.2f} | TP: {tp :.2f} (1:{self .rr_ratio } R:R)"
            )
            return TradeSignal(
                action="SELL",
                symbol=symbol,
                entry_price=close,
                sl_price=sl,
                tp_price=tp,
                atr=atr,
                reason="Bearish EMA trend alignment with favorable RSI momentum",
            )

        return TradeSignal(
            action="HOLD",
            symbol=symbol,
            entry_price=close,
            sl_price=0.0,
            tp_price=0.0,
            atr=atr,
            reason=f"Market consolidation / No confluence (RSI={rsi :.1f}, Close={close :.2f})",
        )
