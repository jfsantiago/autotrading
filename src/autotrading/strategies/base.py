from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

import pandas as pd


class Signal(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Strategy(ABC):
    @abstractmethod
    def generate_signals(self, df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
        """Given an OHLCV DataFrame (indexed by timestamp, with open/high/low/close/volume
        columns), return a Series of Signal values aligned to df.index.
        """
        raise NotImplementedError
