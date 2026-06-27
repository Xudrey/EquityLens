from pathlib import Path
from dataclasses import replace

import pandas as pd
import pytest

from src.config import BASE_CASE
from src.data_loader import load_financial_data
from src.dcf import run_dcf
from src.excel_export import (
    REQUIRED_WORKBOOK_ANCHORS,
    REQUIRED_WORKBOOK_SHEETS,
    export_excel_report,
    validate_workbook_structure,
)
from src.financial_analysis import calculate_financial_metrics, summarize_financial_trends
from src.market_data import get_current_price
from src.memo import generate_investment_memo
from src.sensitivity import revenue_margin_sensitivity, wacc_terminal_growth_sensitivity

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "ndaq_sample_financials.csv"


def test_sample_data_loads_required_columns():
    data = load_financial_data(DATA)
    assert len(data) >= 5
    assert {"year", "revenue", "free_cash_flow", "current_share_price"}.issubset(data.columns)


def test_dcf_runs_and_returns_value():
    data = load_financial_data(DATA)
    result = run_dcf(data, BASE_CASE)
    assert result["fair_value_per_share"] > 0
    assert len(result["projections"]) == BASE_CASE.forecast_years


def test_dcf_rejects_bad_terminal_math():
    data = load_financial_data(DATA)
    with pytest.raises(ValueError):
        run_dcf(data, replace(BASE_CASE, wacc=0.02, terminal_growth=0.03))


def test_memo_generation_works():
    data = load_financial_data(DATA)
    metrics = calculate_financial_metrics(data)
    trends = summarize_financial_trends(metrics)
    dcf = run_dcf(data, BASE_CASE)
    sensitivities = {
        "wacc_terminal_growth": wacc_terminal_growth_sensitivity(data, BASE_CASE),
        "revenue_growth_ebit_margin": revenue_margin_sensitivity(data, BASE_CASE),
    }
    memo = generate_investment_memo(trends, dcf, sensitivities, data_source="Sample Data Fallback", price_source="manual input")
    assert "Executive Summary" in memo
    assert "not investment advice" in memo.lower()


def test_market_data_failure_shape_is_safe(monkeypatch):
    # This does not force network access; it verifies the function returns the expected contract.
    result = get_current_price("NDAQ")
    assert {"ticker", "current_price", "price_source", "price_timestamp", "error_message"}.issubset(result)


def test_excel_export_uses_financial_statement_analysis_structure(tmp_path):
    import openpyxl

    from src.config import COMPANY

    data = load_financial_data(DATA)
    metrics = calculate_financial_metrics(data)
    trends = summarize_financial_trends(metrics)
    dcf = run_dcf(data, BASE_CASE)
    sensitivities = {
        "wacc_terminal_growth": wacc_terminal_growth_sensitivity(data, BASE_CASE),
        "revenue_growth_ebit_margin": revenue_margin_sensitivity(data, BASE_CASE),
    }
    memo = generate_investment_memo(
        trends,
        dcf,
        sensitivities,
        data_source="Sample Data Fallback",
        price_source="manual input",
    )
    output = export_excel_report(
        tmp_path / "equitylens_test.xlsx",
        COMPANY,
        data,
        metrics,
        trends,
        BASE_CASE,
        dcf,
        sensitivities,
        memo,
        metadata={"source": "Sample Data Fallback", "ticker": "NDAQ"},
    )
    workbook = openpyxl.load_workbook(output, read_only=True)
    assert tuple(workbook.sheetnames) == REQUIRED_WORKBOOK_SHEETS
    for sheet_name, cell_checks in REQUIRED_WORKBOOK_ANCHORS.items():
        worksheet = workbook[sheet_name]
        for cell, expected_value in cell_checks.items():
            assert worksheet[cell].value == expected_value
    validate_workbook_structure(output)
