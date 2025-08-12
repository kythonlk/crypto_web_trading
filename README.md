# Crypto & Forex MT4/MT5 Automated Trading Bot

A modular algorithmic trading bot in Python supporting MetaTrader 5 (MT5) with institutional-grade risk management rules ("minimal loss" philosophy) and a test harness using public market data.

## Key Features

1. **Strict Capital Preservation & Risk Controls**:
   - **Dynamic Lot Sizing**: Calculates position volume per trade based strictly on `MAX_RISK_PER_TRADE_PERCENT` (1% default equity risk).
   - **Daily Circuit Breaker**: Auto-halts trading if daily drawdown reaches `MAX_DAILY_DRAWDOWN_PERCENT` (3% default).
   - **ATR-Based Stop-Loss**: Dynamically calculates SL based on market volatility instead of arbitrary static pips.
   - **Breakeven Protection**: Once a trade hits 1R profit, the Stop-Loss is automatically moved to entry price (+ spread buffer) to ensure a risk-free trade.
   - **Trailing Stop**: Trails the market when running in high-momentum conditions.
   - **Spread Guard**: Prevents entering positions during news spikes or widened spreads.

2. **Dual-Mode Broker Engine**:
   - **MT5 Mode**: Connects directly to the MetaTrader 5 desktop terminal via the official Python API.
   - **Test API Paper Mode**: Fetches public OHLCV candles (e.g. Binance public API) and runs real-time paper order execution and SL/TP hit detection without needing MT5 installed or funded.

3. **Strategy Engine**:
   - Fast/Slow EMA Trend Filter (EMA 50 / EMA 200)
   - RSI (14) Momentum Filter
   - ATR (14) Volatility Calculation

---

## Installation & Setup

```bash
# Clone the repository
git clone <repo-url>
cd crypto_web_trading

# Install dependencies
pip install -r requirements.txt

# (Optional for MT5 on Windows)
pip install MetaTrader5
```

Copy the example environment configuration:
```bash
cp .env.example .env
```

---

## Running the Test Bot

To test the entire pipeline with live public market data without needing an MT5 account:
```bash
python test_bot.py
```

To run unit tests:
```bash
python -m pytest tests/test_bot_unit.py -v
```

---

## Running Live MT5 Bot

1. Set `BOT_MODE=MT5` in `.env`.
2. Fill in your `MT5_ACCOUNT`, `MT5_PASSWORD`, and `MT5_SERVER` in `.env`.
3. Launch the bot:
```bash
python main.py
```