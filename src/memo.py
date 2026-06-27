"""Rule-based investment memo generation."""

from typing import Any

import pandas as pd


def _valuation_conclusion(upside: float) -> str:
    if upside > 0.10:
        return "undervalued"
    if upside < -0.10:
        return "overvalued"
    return "fairly valued"


def generate_investment_memo(
    metrics: dict[str, Any],
    dcf_results: dict[str, Any],
    sensitivity_results: dict[str, pd.DataFrame],
    *,
    data_source: str = "SEC EDGAR companyfacts API",
    price_source: str = "manual input",
    quality_notes: pd.DataFrame | None = None,
) -> str:
    """Produce an analyst-style memo without calling an external AI service."""
    upside = dcf_results["upside_downside"]
    conclusion = _valuation_conclusion(upside)
    wacc_table = sensitivity_results["wacc_terminal_growth"]
    operating_table = sensitivity_results["revenue_growth_ebit_margin"]
    low_case = min(wacc_table.min().min(), operating_table.min().min())
    high_case = max(wacc_table.max().max(), operating_table.max().max())

    warning_count = 0
    if quality_notes is not None and not quality_notes.empty and "severity" in quality_notes:
        warning_count = int((quality_notes["severity"] == "Warning").sum())

    sections = [
        ("Executive Summary", f"EquityLens estimates a base-case value of ${dcf_results['fair_value_per_share']:.2f} per share versus a market price of ${dcf_results['current_share_price']:.2f} sourced from {price_source}. This implies {upside:.1%} upside/downside and a {conclusion} conclusion. Historical financials are sourced from {data_source}; the result is not investment advice."),
        ("Business Overview", "Nasdaq, Inc. operates market infrastructure, data, index, workflow, and financial-technology businesses. This MVP analyzes the company at a consolidated level rather than forecasting individual business segments."),
        ("Historical Financial Performance", f"SEC-reported revenue was {metrics['revenue_trend']} at a {metrics['revenue_cagr']:.1%} CAGR. EBIT margin is {metrics['margin_trend']} and reached {metrics['latest_ebit_margin']:.1%}; free-cash-flow margin reached {metrics['latest_fcf_margin']:.1%}."),
        ("Valuation Summary", f"The DCF uses a five-year forecast, a Gordon Growth terminal value, and an explicit cash/debt bridge. Enterprise value is ${dcf_results['enterprise_value']:,.0f} million and equity value is ${dcf_results['equity_value']:,.0f} million."),
        ("Key Sensitivities", f"Across the selected WACC, terminal-growth, revenue-growth, and EBIT-margin cases, indicated value ranges from ${low_case:.2f} to ${high_case:.2f} per share. WACC and terminal growth have the largest impact because terminal value represents a substantial share of enterprise value."),
        ("Risks", f"Key risks include integration execution, leverage, transaction-volume cyclicality, regulatory change, competition, forecast error, and XBRL comparability. The SEC ingestion layer reported {warning_count} data-quality warning(s), which should be reviewed alongside the source tags."),
        ("Final View", f"On the selected assumptions and SEC filing data, NDAQ appears {conclusion}. The conclusion remains sensitive to the market price source, operating assumptions, XBRL tag selection, and the simplified consolidated forecast."),
    ]
    return "\n\n".join(f"{title}\n{text}" for title, text in sections)
