import numpy as np
from .strategy import TrendMomentumStrategy, TradeSignal


class RegimeBreakoutStrategy(TrendMomentumStrategy):
    def evaluate(self, df, symbol):
        hold = TradeSignal("HOLD", symbol, 0, 0, 0, 0, "No clean breakout")
        if df is None or len(df) < 250:
            return hold
        data = self.calculate_indicators(df)
        if not np.isfinite(data[["open", "high", "low", "close"]].to_numpy()).all():
            return hold
        high, low, close = data.high, data.low, data.close
        tr = np.maximum(
            high - low,
            np.maximum((high - close.shift()).abs(), (low - close.shift()).abs()),
        )
        atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        up, down = high.diff(), -low.diff()
        plus = (
            up.where((up > down) & (up > 0), 0).ewm(alpha=1 / 14, adjust=False).mean()
        )
        minus = (
            down.where((down > up) & (down > 0), 0)
            .ewm(alpha=1 / 14, adjust=False)
            .mean()
        )
        dx = 100 * (plus - minus).abs() / (plus + minus).replace(0, np.nan)
        adx = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        # No peeking, fr.
        upper = high.shift(1).rolling(40).max()
        lower = low.shift(1).rolling(40).min()
        baseline = atr.shift(1).rolling(100).median()
        price, volatility = float(close.iloc[-1]), float(atr.iloc[-1])
        metrics = [
            price,
            volatility,
            adx.iloc[-1],
            baseline.iloc[-1],
            upper.iloc[-1],
            lower.iloc[-1],
        ]
        if not np.isfinite(metrics).all() or volatility <= 0 or baseline.iloc[-1] <= 0:
            return hold
        hold.atr = volatility
        if adx.iloc[-1] < 25 or not 0.6 <= volatility / baseline.iloc[-1] <= 2:
            return hold
        fast, slow = data.ema_fast, data.ema_slow
        action = None
        if (
            price > upper.iloc[-1]
            and fast.iloc[-1] > slow.iloc[-1] > slow.iloc[-6]
            and plus.iloc[-1] > minus.iloc[-1]
        ):
            action = "BUY"
        elif (
            price < lower.iloc[-1]
            and fast.iloc[-1] < slow.iloc[-1] < slow.iloc[-6]
            and minus.iloc[-1] > plus.iloc[-1]
        ):
            action = "SELL"
        if action is None:
            return hold
        direction = 1 if action == "BUY" else -1
        distance = volatility * max(2, self.atr_multiplier)
        return TradeSignal(
            action,
            symbol,
            price,
            price - direction * distance,
            price + direction * distance * self.rr_ratio,
            volatility,
            "Donchian breakout confirmed by ADX, EMA slope, and volatility regime",
        )
