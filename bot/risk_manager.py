import logging
from datetime import datetime, date, timezone
from typing import Optional, Dict
from config import config

logger = logging.getLogger("RiskManager")


class RiskManager:
    """
    Capital Preservation & Risk Management Engine.
    Ensures that every trade risks only a controlled fraction of equity,
    enforces daily loss stop-outs, and blocks trading during wide spreads.
    """

    def __init__(
        self,
        max_risk_per_trade_pct: float = config.max_risk_per_trade_pct,
        max_daily_drawdown_pct: float = config.max_daily_drawdown_pct,
        max_spread_points: float = config.max_spread_points,
        max_open_positions: int = config.max_open_positions,
    ):
        self.max_risk_pct = max_risk_per_trade_pct
        self.max_daily_drawdown_pct = max_daily_drawdown_pct
        self.max_spread_points = max_spread_points
        self.max_open_positions = max_open_positions

        self.current_day: date = datetime.now(timezone.utc).date()
        self.starting_day_equity: Optional[float] = None
        self.trading_halted_today: bool = False

    def reset_daily_tracker_if_needed(self, current_equity: float):
        today = datetime.now(timezone.utc).date()
        if self.current_day != today or self.starting_day_equity is None:
            self.current_day = today
            self.starting_day_equity = current_equity
            self.trading_halted_today = False
            logger.info(f"Daily Risk Tracker reset. New day equity baseline: ${current_equity:,.2f}")

    def check_daily_drawdown(self, current_equity: float) -> bool:
        """
        Circuit breaker check: Returns True if trading is safe,
        False if daily drawdown limit has been breached.
        """
        self.reset_daily_tracker_if_needed(current_equity)

        if self.starting_day_equity and self.starting_day_equity > 0:
            drawdown_pct = ((self.starting_day_equity - current_equity) / self.starting_day_equity) * 100.0
            if drawdown_pct >= self.max_daily_drawdown_pct:
                if not self.trading_halted_today:
                    logger.warning(
                        f"[CIRCUIT BREAKER] Daily loss reached {drawdown_pct:.2f}% "
                        f"(Limit: {self.max_daily_drawdown_pct}%). Trading halted for today."
                    )
                    self.trading_halted_today = True
                return False
        return not self.trading_halted_today

    def is_spread_acceptable(self, symbol_info: Dict) -> bool:
        """Check if current spread is within acceptable limits."""
        spread = symbol_info.get("spread", 0.0)
        if spread > self.max_spread_points:
            logger.warning(
                f"[SPREAD FILTER] Current spread ({spread}) exceeds threshold ({self.max_spread_points}). "
                f"Trade entry aborted to preserve capital."
            )
            return False
        return True

    def calculate_position_size(
        self,
        equity: float,
        entry_price: float,
        sl_price: float,
        symbol_info: Dict,
    ) -> float:
        """
        Calculate position volume based on strict fractional equity risk.
        Formula:
            Risk Amount ($) = Equity * (Risk_Pct / 100)
            SL Distance ($ per unit) = abs(entry - sl)
            Position Volume = Risk Amount / SL Distance
        Normalized to broker min_lot, max_lot, and volume_step.
        """
        if entry_price <= 0 or sl_price <= 0:
            return 0.0

        sl_distance = abs(entry_price - sl_price)
        if sl_distance <= 0:
            return 0.0

        # Maximum dollar amount willing to lose on this trade
        risk_cash = equity * (self.max_risk_pct / 100.0)

        # Base volume
        raw_volume = risk_cash / sl_distance

        vol_min = symbol_info.get("volume_min", 0.01)
        vol_step = symbol_info.get("volume_step", 0.01)
        vol_max = symbol_info.get("volume_max", 10.0)

        # Normalize to lot steps
        steps = round(raw_volume / vol_step)
        normalized_volume = steps * vol_step
        normalized_volume = max(vol_min, min(normalized_volume, vol_max))
        normalized_volume = round(normalized_volume, 2)

        expected_risk = normalized_volume * sl_distance
        logger.info(
            f"[POSITION SIZING] Equity: ${equity:,.2f} | Risk: {self.max_risk_pct}% (${risk_cash:.2f}) | "
            f"SL Distance: {sl_distance:.2f} | Lot Size: {normalized_volume:.2f} (Max Loss: ${expected_risk:.2f})"
        )
        return normalized_volume

    def can_open_new_trade(
        self,
        current_equity: float,
        open_positions_count: int,
        symbol_info: Dict,
    ) -> bool:
        """All-in-one risk gate check prior to order submission."""
        # 1. Check Circuit Breaker
        if not self.check_daily_drawdown(current_equity):
            return False

        # 2. Check Concurrency / Max Positions
        if open_positions_count >= self.max_open_positions:
            logger.debug(f"[EXPOSURE LIMIT] Open positions ({open_positions_count}) >= limit ({self.max_open_positions}).")
            return False

        # 3. Check Spread
        if not self.is_spread_acceptable(symbol_info):
            return False

        return True
