import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class TradingConfig:
    # Broker & Terminal
    bot_mode: str = os.getenv("BOT_MODE", "TEST_API").upper()
    mt5_account: int = int(os.getenv("MT5_ACCOUNT", "0"))
    mt5_password: str = os.getenv("MT5_PASSWORD", "")
    mt5_server: str = os.getenv("MT5_SERVER", "")
    mt5_path: str = os.getenv("MT5_PATH", "")

    # Symbol & Market
    symbol: str = os.getenv("TRADING_SYMBOL", "BTCUSDT")
    timeframe: str = os.getenv("TIMEFRAME", "M15")

    # Capital Preservation & Risk Controls
    # 1. Never risk more than 1% of account equity per trade
    max_risk_per_trade_pct: float = float(os.getenv("MAX_RISK_PER_TRADE_PERCENT", "1.0"))
    # 2. Daily circuit breaker: halt all trading if day's equity drops by 3%
    max_daily_drawdown_pct: float = float(os.getenv("MAX_DAILY_DRAWDOWN_PERCENT", "3.0"))
    # 3. Target at least 1:2 Risk to Reward
    risk_reward_ratio: float = float(os.getenv("RISK_REWARD_RATIO", "2.0"))
    # 4. Stop Loss dynamically calculated as ATR * multiplier
    atr_multiplier_sl: float = float(os.getenv("ATR_MULTIPLIER_SL", "1.5"))
    # 5. Breakeven trigger: move SL to entry price once trade reaches 1R profit
    breakeven_r_trigger: float = float(os.getenv("BREAKEVEN_R_TRIGGER", "1.0"))
    # 6. Trailing stop enabled
    trailing_stop_enabled: bool = os.getenv("TRAILING_STOP_ENABLED", "True").lower() == "true"
    # 7. Spread filter: avoid opening trades during news spikes or widened spreads
    max_spread_points: float = float(os.getenv("MAX_SPREAD_POINTS", "30.0"))
    # 8. Exposure cap: limit concurrent open positions
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "2"))

    # Bot runtime loop
    poll_interval_seconds: float = float(os.getenv("POLL_INTERVAL_SECONDS", "5.0"))


# Global singleton instance
config = TradingConfig()
