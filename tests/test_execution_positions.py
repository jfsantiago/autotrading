from autotrading.execution.positions import PositionSide, get_position_state


class FakeClient:
    def __init__(self, positions):
        self._positions = positions

    def fetch_positions(self, symbols):
        return self._positions


def test_empty_list_is_flat():
    client = FakeClient([])
    state = get_position_state(client, "BTC/USDT")
    assert state.side == PositionSide.FLAT
    assert state.size == 0.0


def test_zero_contracts_is_flat():
    client = FakeClient([{"contracts": 0, "side": "long", "entryPrice": 100.0}])
    state = get_position_state(client, "BTC/USDT")
    assert state.side == PositionSide.FLAT


def test_long_position_parsed():
    client = FakeClient([{"contracts": 2.5, "side": "long", "entryPrice": 91000.0}])
    state = get_position_state(client, "BTC/USDT")
    assert state.side == PositionSide.LONG
    assert state.size == 2.5
    assert state.entry_price == 91000.0


def test_short_position_parsed():
    client = FakeClient([{"contracts": 1.2, "side": "short", "entryPrice": 92000.0}])
    state = get_position_state(client, "BTC/USDT")
    assert state.side == PositionSide.SHORT
    assert state.size == 1.2
