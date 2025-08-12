"""
Test Bot Runner
Demonstrates live market data fetching, indicator analysis, risk-controlled lot sizing,
and paper trade lifecycle simulation without requiring MetaTrader credentials.
"""

import time
import logging
from bot.mock_broker import PublicApiMockBroker
from bot.risk_manager import RiskManager
from bot.strategy import TrendMomentumStrategy, TradeSignal
from bot.position_tracker import PositionTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("TestBot")


def run_live_public_api_test():
    print("=" * 70)
    print("        STARTING TEST BOT (PUBLIC API PAPER SIMULATION)         ")
    print("=" * 70)

    symbol = "BTCUSDT"
    broker = PublicApiMockBroker(initial_balance=10000.0, symbol=symbol)
    risk_manager = RiskManager(
        max_risk_per_trade_pct=1.0,
        max_daily_drawdown_pct=3.0,
        max_spread_points=25.0,
        max_open_positions=2,
    )
    strategy = TrendMomentumStrategy(
        fast_ema=20,
        slow_ema=50,
        rsi_period=14,
        atr_period=14,
        atr_multiplier_sl=1.5,
        risk_reward_ratio=2.0,
    )
    tracker = PositionTracker(
        broker=broker,
        breakeven_r_trigger=1.0,
        trailing_stop_enabled=True,
    )

    # 1. Connect
    assert broker.connect(), "Failed to connect to public API mock broker"

    # 2. Fetch live candles from public Binance API
    print(f"\n[1/5] Fetching live market candles for {symbol}...")
    candles = broker.get_candles(symbol, timeframe="M15", count=100)
    print(f"      Fetched {len(candles)} candles. Latest Close: ${candles.iloc[-1]['close']:,.2f}")

    # 3. Calculate indicators & Evaluate strategy
    print("\n[2/5] Calculating EMA, RSI, and ATR indicators...")
    indicators_df = strategy.calculate_indicators(candles, fast_ema=20, slow_ema=50)
    last = indicators_df.iloc[-1]
    print(f"      EMA(20): {last['ema_fast']:.2f} | EMA(50): {last['ema_slow']:.2f}")
    print(f"      RSI(14): {last['rsi']:.2f} | ATR(14): {last['atr']:.2f}")

    signal = strategy.evaluate(candles, symbol)
    print(f"      Strategy Signal: {signal.action} ({signal.reason})")

    # If the current market is in HOLD, generate a synthetic test BUY signal to demonstrate the full risk pipeline
    if signal.action == "HOLD":
        print("\n[3/5] (Market is consolidating - triggering demo signal to verify execution & risk pipeline)")
        close = last["close"]
        atr = last["atr"] if last["atr"] > 0 else close * 0.01
        sl = close - (atr * 1.5)
        tp = close + (atr * 3.0)
        signal = TradeSignal(
            action="BUY",
            symbol=symbol,
            entry_price=close,
            sl_price=sl,
            tp_price=tp,
            atr=atr,
            reason="Validation test order",
        )

    # 4. Sizing calculation
    balance, equity = broker.get_balance_and_equity()
    sym_info = broker.get_symbol_info(symbol)

    print(f"\n[4/5] Risk Calculation for Equity ${equity:,.2f}...")
    volume = risk_manager.calculate_position_size(
        equity=equity,
        entry_price=signal.entry_price,
        sl_price=signal.sl_price,
        symbol_info=sym_info,
    )
    sl_dist = abs(signal.entry_price - signal.sl_price)
    max_risk = volume * sl_dist
    risk_pct = (max_risk / equity) * 100
    print(f"      Calculated Volume: {volume:.2f} lots")
    print(f"      Max Potential Loss: ${max_risk:.2f} ({risk_pct:.2f}% of equity)")
    assert risk_pct <= 1.05, f"Risk {risk_pct}% exceeded 1% allowance!"

    # 5. Execute simulated order
    print("\n[5/5] Executing Simulated Order...")
    ticket = broker.place_order(
        symbol=symbol,
        order_type=signal.action,
        volume=volume,
        sl=signal.sl_price,
        tp=signal.tp_price,
        comment="test_pipeline",
    )
    tracker.register_position(ticket, signal.entry_price, signal.sl_price)

    positions = broker.get_positions(symbol)
    print(f"      Open Positions: {len(positions)}")
    for pos in positions:
        print(f"      -> Ticket #{pos.ticket}: {pos.order_type} {pos.volume} @ {pos.open_price:.2f} | SL: {pos.sl:.2f} | TP: {pos.tp:.2f}")

    # 6. Simulate favorable price move to verify Breakeven lock
    print("\n--- Verifying Breakeven Protection Mechanism ---")
    pos_item = positions[0]
    target_price = pos_item.open_price + (sl_dist * 1.3)
    broker.set_simulated_price(target_price)
    print(f"      Simulating price rise to {target_price:.2f} (+1.3R profit)...")
    tracker.update_positions(symbol, current_atr=signal.atr)

    updated_pos = broker.get_positions(symbol)[0]
    print(f"      Updated SL: {updated_pos.sl:.2f} (Entry was: {pos_item.open_price:.2f})")
    assert updated_pos.sl >= pos_item.open_price, "Breakeven SL should be at or above entry price!"
    print("      [PASSED] Stop Loss successfully moved to Breakeven to guarantee risk-free trade!")

    # 7. Simulate Take Profit exit
    print("\n--- Verifying Take Profit Exit ---")
    broker.set_simulated_price(signal.tp_price + 10.0)
    broker.get_balance_and_equity()
    remaining = broker.get_positions(symbol)
    print(f"      Remaining Open Positions: {len(remaining)}")
    new_balance, new_equity = broker.get_balance_and_equity()
    print(f"      Final Balance: ${new_balance:,.2f} | Realized Profit: ${new_balance - 10000.0:+,.2f}")
    assert len(remaining) == 0, "Position should be closed when TP is reached!"

    print("\n" + "=" * 70)
    print("               TEST BOT VERIFICATION COMPLETE: ALL PASS        ")
    print("=" * 70)


if __name__ == "__main__":
    run_live_public_api_test()
