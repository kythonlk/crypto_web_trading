import logging
from typing import Dict
from .broker_interface import BrokerInterface, Position
from config import config

logger = logging.getLogger("PositionTracker")


class PositionTracker:

    def __init__(
        self,
        broker: BrokerInterface,
        breakeven_r_trigger: float = config.breakeven_r_trigger,
        trailing_stop_enabled: bool = config.trailing_stop_enabled,
    ):
        self.broker = broker
        self.breakeven_r = breakeven_r_trigger
        self.trailing_enabled = trailing_stop_enabled

        self.initial_risks: Dict[int, float] = {}

    def register_position(self, ticket: int, open_price: float, initial_sl: float):

        if initial_sl > 0:
            risk = abs(open_price - initial_sl)
            self.initial_risks[ticket] = risk
            logger.info(
                f"Position #{ticket } registered with initial risk distance: {risk :.2f}"
            )

    def update_positions(self, symbol: str, current_atr: float = 0.0):

        positions = self.broker.get_positions(symbol)
        if not positions:
            return

        for pos in positions:

            if pos.ticket not in self.initial_risks and pos.sl > 0:
                self.initial_risks[pos.ticket] = abs(pos.open_price - pos.sl)

            risk_dist = self.initial_risks.get(pos.ticket, 0.0)
            if risk_dist <= 0:
                continue

            current_price = pos.current_price
            open_price = pos.open_price

            if pos.order_type == "BUY":
                favorable_move = current_price - open_price
                r_multiple = favorable_move / risk_dist

                if r_multiple >= self.breakeven_r and pos.sl < open_price:
                    new_sl = open_price + (risk_dist * 0.05)
                    logger.info(
                        f"[BREAKEVEN TRIGGER] Position #{pos .ticket } (BUY) hit {r_multiple :.2f}R. "
                        f"Moving SL from {pos .sl :.2f} to Breakeven {new_sl :.2f} to guarantee risk-free trade."
                    )
                    self.broker.modify_position(pos.ticket, sl=new_sl, tp=pos.tp)
                    pos.sl = new_sl

                elif self.trailing_enabled and r_multiple >= 1.5 and current_atr > 0:
                    trail_sl = current_price - (current_atr * 1.5)
                    if trail_sl > pos.sl:
                        logger.info(
                            f"[TRAILING STOP] Position #{pos .ticket } (BUY) at {current_price :.2f}. "
                            f"Trailing SL adjusted from {pos .sl :.2f} to {trail_sl :.2f}."
                        )
                        self.broker.modify_position(pos.ticket, sl=trail_sl, tp=pos.tp)
                        pos.sl = trail_sl

            elif pos.order_type == "SELL":
                favorable_move = open_price - current_price
                r_multiple = favorable_move / risk_dist

                if r_multiple >= self.breakeven_r and (
                    pos.sl == 0 or pos.sl > open_price
                ):
                    new_sl = open_price - (risk_dist * 0.05)
                    logger.info(
                        f"[BREAKEVEN TRIGGER] Position #{pos .ticket } (SELL) hit {r_multiple :.2f}R. "
                        f"Moving SL from {pos .sl :.2f} to Breakeven {new_sl :.2f} to guarantee risk-free trade."
                    )
                    self.broker.modify_position(pos.ticket, sl=new_sl, tp=pos.tp)
                    pos.sl = new_sl

                elif self.trailing_enabled and r_multiple >= 1.5 and current_atr > 0:
                    trail_sl = current_price + (current_atr * 1.5)
                    if pos.sl == 0 or trail_sl < pos.sl:
                        logger.info(
                            f"[TRAILING STOP] Position #{pos .ticket } (SELL) at {current_price :.2f}. "
                            f"Trailing SL adjusted from {pos .sl :.2f} to {trail_sl :.2f}."
                        )
                        self.broker.modify_position(pos.ticket, sl=trail_sl, tp=pos.tp)
                        pos.sl = trail_sl
