import sys
import time
import signal
import logging
from config import config
from bot.broker_interface import BrokerInterface
from bot.mt5_broker import MT5Broker
from bot.mock_broker import PublicApiMockBroker
from bot.risk_manager import RiskManager
from bot.strategy import TrendMomentumStrategy
from bot.position_tracker import PositionTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("MainBot")


class TradingBot:
    def __init__(self):
        self.running = False

        # 1. Instantiate appropriate broker engine
        if config.bot_mode == "MT5":
            logger.info("Initializing Live MetaTrader 5 Engine...")
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

        # 2. Risk & Strategy subsystems
        self.risk_manager = RiskManager(
            max_risk_per_trade_pct=config.max_risk_per_trade_pct,
            max_daily_drawdown_pct=config.max_daily_drawdown_pct,
            max_spread_points=config.max_spread_points,
            max_open_positions=config.max_open_positions,
        )
        self.strategy = TrendMomentumStrategy(
            atr_multiplier_sl=config.atr_multiplier_sl,
            risk_reward_ratio=config.risk_reward_ratio,
        )
        self.tracker = PositionTracker(
            broker=self.broker,
            breakeven_r_trigger=config.breakeven_r_trigger,
            trailing_stop_enabled=config.trailing_stop_enabled,
        )

    def start(self):
        if not self.broker.connect():
            logger.error("Broker connection failed. Exiting.")
            return

        self.running = True
        logger.info("=" * 60)
        logger.info(f"TRADING BOT STARTED | Mode: {config.bot_mode} | Symbol: {config.symbol}")
        logger.info(f"Risk Rules: Max {config.max_risk_per_trade_pct}%/trade | Max Daily DD: {config.max_daily_drawdown_pct}% | R:R: 1:{config.risk_reward_ratio}")
        logger.info("=" * 60)

        # Register signals for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

        iteration = 0
        while self.running:
            try:
                iteration += 1
                self._run_iteration(iteration)
            except Exception as e:
                logger.exception(f"Unexpected error in trading loop: {e}")

            time.sleep(config.poll_interval_seconds)

        self.broker.disconnect()
        logger.info("Trading Bot stopped gracefully.")

    def _run_iteration(self, iteration: int):
        balance, equity = self.broker.get_balance_and_equity()
        open_positions = self.broker.get_positions(config.symbol)
        sym_info = self.broker.get_symbol_info(config.symbol)

        if not sym_info:
            logger.warning(f"Could not retrieve symbol info for {config.symbol}")
            return

        # Fetch recent market candles
        candles = self.broker.get_candles(config.symbol, config.timeframe, count=100)
        signal = self.strategy.evaluate(candles, config.symbol)

        # 1. Update active positions (apply breakeven locks & trailing stops)
        self.tracker.update_positions(config.symbol, current_atr=signal.atr)

        # Periodic status logging
        if iteration % 6 == 1:
            logger.info(
                f"[STATUS] Balance: ${balance:,.2f} | Equity: ${equity:,.2f} | "
                f"Open Positions: {len(open_positions)}/{config.max_open_positions} | Signal: {signal.action}"
            )

        # 2. Check if we have a trade signal
        if signal.action not in ["BUY", "SELL"]:
            return

        # 3. Capital Preservation Gate: Check risk limits
        can_trade = self.risk_manager.can_open_new_trade(
            current_equity=equity,
            open_positions_count=len(open_positions),
            symbol_info=sym_info,
        )
        if not can_trade:
            return

        # 4. Calculate dynamic position size based on exact 1% equity risk
        volume = self.risk_manager.calculate_position_size(
            equity=equity,
            entry_price=signal.entry_price,
            sl_price=signal.sl_price,
            symbol_info=sym_info,
        )
        if volume <= 0:
            logger.warning("Calculated volume is zero or invalid. Trade aborted.")
            return

        # 5. Execute Order
        ticket = self.broker.place_order(
            symbol=config.symbol,
            order_type=signal.action,
            volume=volume,
            sl=signal.sl_price,
            tp=signal.tp_price,
            comment="algo_trend_follow",
        )

        if ticket:
            self.tracker.register_position(ticket, signal.entry_price, signal.sl_price)

    def _handle_exit(self, signum, frame):
        logger.info("Shutdown signal received. Wrapping up...")
        self.running = False


if __name__ == "__main__":
    bot = TradingBot()
    bot.start()
