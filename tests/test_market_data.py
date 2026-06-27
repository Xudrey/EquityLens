import sys
import types
from unittest.mock import patch

import pandas as pd

from src.market_data import get_current_price


def _history(prices):
    index = pd.to_datetime(["2026-06-19 15:58:00-04:00", "2026-06-19 15:59:00-04:00"])
    return pd.DataFrame({"Close": prices}, index=index)


def test_intraday_price_success():
    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            return _history([88.10, 88.25])

    with patch.dict(sys.modules, {"yfinance": types.SimpleNamespace(Ticker=Ticker)}):
        result = get_current_price("ndaq")
    assert result["ticker"] == "NDAQ"
    assert result["current_price"] == 88.25
    assert result["price_source"] == "yfinance"
    assert "2026-06-19" in result["price_timestamp"]
    assert result["error_message"] is None


def test_daily_price_fallback():
    class Ticker:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):
            if kwargs["interval"] == "1m":
                return pd.DataFrame()
            return _history([87.50, 87.90])

    with patch.dict(sys.modules, {"yfinance": types.SimpleNamespace(Ticker=Ticker)}):
        result = get_current_price("NDAQ")
    assert result["current_price"] == 87.90
    assert result["error_message"] is None


def test_market_failure_returns_error_instead_of_raising():
    class Ticker:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):
            raise ConnectionError("network unavailable")

    with patch.dict(sys.modules, {"yfinance": types.SimpleNamespace(Ticker=Ticker)}):
        result = get_current_price("NDAQ")
    assert result["current_price"] is None
    assert result["price_source"] is None
    assert "network unavailable" in result["error_message"]
