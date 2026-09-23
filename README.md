# Orbit trading workspace

Forex and crypto strategy experiments with an MT5 demo-only adapter and a Tailwind CDN dashboard. No profitability claims: neither strategy has been validated on historical or forward market data.

## Dashboard

Run `python -m http.server 8000`, then open `http://localhost:8000`.
Tailwind and fonts require internet access. Quotes, positions, and equity are illustrative. Filters, chart periods, settings dialogs, strategy previews, and JSON export work locally. Dashboard controls do not execute trades or update Python settings.

## Bot

Install `pip install -r requirements.txt`. Copy `.env.example` to `.env` and keep credentials private.

- `STRATEGY=trend`: EMA 50/200, RSI, ATR stop and target.
- `STRATEGY=breakout`: 40-bar Donchian breakout, ADX strength, EMA slope and alignment, directional movement, and ATR volatility regime. Experimental.
- `BOT_MODE=TEST_API`: crypto paper broker. Its network fallback can use synthetic prices; this is not a performance backtest.
- `BOT_MODE=MT5`: requires the MT5 Python package and a local terminal, normally on Windows. Specify the exact demo login, broker server, and trading password. Investor passwords cannot place orders.
- `TRADING_SYMBOL`: one broker symbol per process, such as EURUSD or BTCUSD. Availability, naming, and contract sizes depend on the broker; MT5 crypto symbols are often CFDs, not spot holdings.

Run `python main.py`. MT5 entry signals use completed candles, sufficient EMA history, and one attempt per candle per process. The adapter rejects real accounts and mismatched logins, rounds volume down, and runs broker order preflight.

Risk limits are estimates: gaps, slippage, and costs can exceed stop-based sizing. Daily drawdown state and candle deduplication are in memory and reset on restart. Position limits are per symbol, not an account-wide portfolio cap. Do not run multiple instances as a portfolio system. Broker tick values drive lot sizing and must be valid. Test using the actual broker's symbols and costs before relying on any result.

## Checks

`python -m pytest tests -q`

`node --check app.js`

MT5 account execution and dashboard integration still require a connected terminal; the static page does not provide that bridge.
