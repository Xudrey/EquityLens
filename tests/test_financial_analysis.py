import pandas as pd
import pytest

from src.financial_analysis import calculate_financial_metrics, calculate_revenue_cagr


def test_revenue_cagr():
    data = pd.DataFrame({"year": [2020, 2022], "revenue": [100.0, 121.0]})
    assert calculate_revenue_cagr(data) == pytest.approx(0.10)


def test_ratio_calculations():
    data = pd.DataFrame({
        "year": [2024], "revenue": [100.0], "ebit": [20.0], "net_income": [10.0],
        "free_cash_flow": [12.0], "total_debt": [36.0],
    })
    result = calculate_financial_metrics(data).iloc[0]
    assert result["ebit_margin"] == pytest.approx(0.20)
    assert result["fcf_conversion"] == pytest.approx(1.20)
    assert result["debt_to_fcf"] == pytest.approx(3.0)

