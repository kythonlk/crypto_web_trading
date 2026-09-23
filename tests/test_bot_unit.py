import pytest
import pandas as pd
import numpy as np
from bot.risk_manager import RiskManager
from bot.strategy import TrendMomentumStrategy
from bot.mock_broker import PublicApiMockBroker
from bot.position_tracker import PositionTracker


def test_position_sizing_respects_max_risk():
    rm = RiskManager(max_risk_per_trade_pct=1.0)
    equity = 10000.0
    entry_price = 50000.0
    sl_price = 49500.0
    sym_info = {"volume_min": 0.01, "volume_step": 0.01, "volume_max": 10.0}

    volume = rm.calculate_position_size(equity, entry_price, sl_price, sym_info)
    expected_risk = volume * (entry_price - sl_price)
    assert volume == 0.20
    assert expected_risk == 100.0


def test_daily_drawdown_circuit_breaker():
    rm = RiskManager(max_daily_drawdown_pct=3.0)

    assert rm.check_daily_drawdown(10000.0) is True

    assert rm.check_daily_drawdown(9800.0) is True

    assert rm.check_daily_drawdown(9690.0) is False

    assert rm.trading_halted_today is True


def test_strategy_indicator_calculation():

    prices = [100.0 + i * 0.5 for i in range(100)]
    df = pd.DataFrame(
        {
            "time": pd.date_range("2025-01-01", periods=100, freq="15min"),
            "open": prices,
            "high": [p + 1.0 for p in prices],
            "low": [p - 1.0 for p in prices],
            "close": prices,
            "volume": [100.0] * 100,
        }
    )

    ind = TrendMomentumStrategy.calculate_indicators(df, fast_ema=20, slow_ema=50)
    assert "ema_fast" in ind.columns
    assert "ema_slow" in ind.columns
    assert "rsi" in ind.columns
    assert "atr" in ind.columns
    assert ind.iloc[-1]["ema_fast"] > ind.iloc[-1]["ema_slow"]


def test_breakeven_trigger_moves_stop_loss():
    broker = PublicApiMockBroker(initial_balance=10000.0, symbol="BTCUSDT")
    broker.connect()
    tracker = PositionTracker(broker=broker, breakeven_r_trigger=1.0)

    broker.set_simulated_price(50000.0)
    ticket = broker.place_order(
        symbol="BTCUSDT", order_type="BUY", volume=0.1, sl=49000.0, tp=53000.0
    )
    tracker.register_position(ticket, open_price=50000.0, initial_sl=49000.0)

    broker.set_simulated_price(51500.0)
    tracker.update_positions("BTCUSDT", current_atr=200.0)

    pos = broker.get_positions("BTCUSDT")[0]
    assert (
        pos.sl >= 50000.0
    ), f"Stop loss should be moved to breakeven or above, got {pos .sl }"
