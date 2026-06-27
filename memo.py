"""Rule-based investment memo generation for the MVP."""

from typing import Any
import pandas as pd


def valuation_conclusion(upside: float) -> str:
    if upside > 0.10:
        return "undervalued"
    if upside < -0.10:
        return "overvalued"
    return "fairly valued"


def generate_investment_memo(metrics: dict[str, Any], dcf_results: dict[str, Any], sensitivity_results: dict[str, pd.DataFrame], *, data_source: str, price_source: str, key_drivers: list[dict[str, str]] | None = None) -> str:
    """Generate a plain-English, educational memo without a paid AI API."""
    upside = dcf_results["upside_downside"]
    conclusion = valuation_conclusion(upside)
    wacc_table = sensitivity_results["wacc_terminal_growth"]
    operating_table = sensitivity_results["revenue_growth_ebit_margin"]
    low_case = min(wacc_table.min().min(), operating_table.min().min())
    high_case = max(wacc_table.max().max(), operating_table.max().max())
    drivers_text = "; ".join([f"{d['driver']}: {d['valuation_effect']}" for d in (key_drivers or [])[:5]])
    sections = [
        ("Executive Summary", f"Based on the current assumptions, the model suggests a fair value of ${dcf_results['fair_value_per_share']:.2f} per share versus a current price of ${dcf_results['current_share_price']:.2f}. That implies {upside:.1%} upside/downside and a scenario label of {conclusion}. This is a valuation scenario, not investment advice."),
        ("Business Overview", "Nasdaq, Inc. operates exchange, market technology, data, index, and financial-technology businesses. This MVP evaluates the company at a consolidated level rather than forecasting each segment separately."),
        ("Historical Financial Performance", f"Revenue has {metrics['revenue_trend']} across the selected period, with a revenue CAGR of {metrics['revenue_cagr']:.1%}. EBIT margin has {metrics['margin_trend']}, and free cash flow was {metrics['fcf_trend']}"),
        ("Valuation Summary", f"The DCF uses a five-year forecast, unlevered free cash flow, a Gordon Growth terminal value, and a cash/debt equity bridge. Enterprise value is ${dcf_results['enterprise_value']:,.0f} million and equity value is ${dcf_results['equity_value']:,.0f} million."),
        ("Sensitivity Analysis", f"Across the selected WACC, terminal-growth, revenue-growth, and EBIT-margin cases, fair value ranges from ${low_case:.2f} to ${high_case:.2f} per share. This shows that the result is highly assumption-driven, especially around discount rate and terminal value."),
        ("Key Value Drivers", drivers_text or "The key valuation drivers are revenue growth, margin stability, free cash flow conversion, leverage, WACC, and terminal growth."),
        ("Risks and Limitations", f"Financial statement data source: {data_source}. Market price source: {price_source}. SEC XBRL tags can vary by year, yfinance prices may be delayed, and the model is simplified for education."),
        ("Final View", f"Based on the current assumptions, NDAQ appears {conclusion} in this scenario. The result should be interpreted as a structured valuation exercise, not a buy/sell recommendation."),
    ]
    return "\n\n".join(f"{title}\n{text}" for title, text in sections)
