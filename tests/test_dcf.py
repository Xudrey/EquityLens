from pathlib import Path

import pytest

from src.config import BASE_CASE, DCFAssumptions
from src.data_loader import load_financial_data
from src.dcf import run_dcf


DATA = Path(__file__).resolve().parents[1] / "data" / "ndaq_sample_financials.csv"


def test_dcf_returns_five_forecast_years():
    result = run_dcf(load_financial_data(DATA), BASE_CASE)
    assert len(result["projections"]) == 5
    assert result["fair_value_per_share"] > 0


def test_wacc_must_exceed_terminal_growth():
    bad = DCFAssumptions(wacc=0.02, terminal_growth=0.03)
    with pytest.raises(ValueError, match="WACC"):
        run_dcf(load_financial_data(DATA), bad)

