import pandas as pd
import pytest
from types import SimpleNamespace
from unittest.mock import Mock
from bot import mt5_broker
from bot.risk_manager import RiskManager
from bot.regime_strategy import RegimeBreakoutStrategy
from bot.strategy import TrendMomentumStrategy


@pytest.mark.parametrize('login,mode', [(123, 2), (456, 0)])
def test_reject_real_or_wrong_account(monkeypatch, login, mode):
    api = Mock()
    api.initialize.return_value = True
    api.ACCOUNT_TRADE_MODE_DEMO = 0
    api.account_info.return_value = SimpleNamespace(login=login, trade_mode=mode)
    monkeypatch.setattr(mt5_broker, 'MT5_AVAILABLE', True)
    monkeypatch.setattr(mt5_broker, 'mt5', api)
    assert not mt5_broker.MT5Broker(account=123).connect()
    api.shutdown.assert_called_once()
    api.order_send.assert_not_called()


def test_forex_lot_risk():
    info = dict(
        volume_min=0.01,
        volume_max=100,
        volume_step=0.01,
        trade_tick_size=0.00001,
        trade_tick_value_loss=1,
    )
    volume = RiskManager(max_risk_per_trade_pct=1).calculate_position_size(
        10000, 1.1, 1.097, info
    )
    assert 0 < volume <= 0.33
    assert volume * 0.003 / 0.00001 <= 100


def test_minimum_lot_is_not_forced():
    info = dict(volume_min=1, volume_max=100, volume_step=1)
    assert RiskManager().calculate_position_size(10, 100, 90, info) == 0


def test_strategy_requires_full_warmup():
    df = pd.DataFrame({"close": [100.0] * 100})
    assert TrendMomentumStrategy().evaluate(df, "EURUSD").action == "HOLD"
    assert RegimeBreakoutStrategy().evaluate(df, "BTCUSD").action == "HOLD"


def test_breakout_both_directions_and_flat_market():
    for direction, expected in [(1, "BUY"), (-1, "SELL"), (0, "HOLD")]:
        prices = [100 + direction * i * 0.1 for i in range(300)]
        prices[-1] += direction * 0.5
        df = pd.DataFrame(
            dict(
                open=prices,
                close=prices,
                high=[p + 0.2 for p in prices],
                low=[p - 0.2 for p in prices],
            )
        )
        signal = RegimeBreakoutStrategy().evaluate(df, "TEST")
        assert signal.action == expected
        if direction:
            assert (signal.entry_price - signal.sl_price) * direction > 0
            assert (signal.tp_price - signal.entry_price) * direction > 0
