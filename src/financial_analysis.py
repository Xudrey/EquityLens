"""Historical financial ratio and trend calculations."""

from typing import Any

import numpy as np
import pandas as pd


def calculate_revenue_cagr(data: pd.DataFrame) -> float:
    """Calculate revenue CAGR from the first to the last annual observation."""
    if len(data) < 2:
        return np.nan
    years = int(data["year"].iloc[-1] - data["year"].iloc[0])
    start = float(data["revenue"].iloc[0])
    end = float(data["revenue"].iloc[-1])
    if years <= 0 or start <= 0:
        return np.nan
    return (end / start) ** (1 / years) - 1


def calculate_financial_metrics(data: pd.DataFrame) -> pd.DataFrame:
    """Add core profitability, growth, conversion, and leverage metrics."""
    metrics = data.copy()
    metrics["revenue_growth"] = metrics["revenue"].pct_change()
    metrics["ebit_margin"] = metrics["ebit"] / metrics["revenue"]
    metrics["net_margin"] = metrics["net_income"] / metrics["revenue"]
    metrics["fcf_margin"] = metrics["free_cash_flow"] / metrics["revenue"]
    metrics["fcf_conversion"] = metrics["free_cash_flow"] / metrics["net_income"]
    metrics["debt_to_fcf"] = metrics["total_debt"] / metrics["free_cash_flow"]
    return metrics.replace([np.inf, -np.inf], np.nan)


def summarize_financial_trends(metrics: pd.DataFrame) -> dict[str, Any]:
    """Return portfolio-friendly headline metrics and plain-English trends."""
    latest = metrics.iloc[-1]
    cagr = calculate_revenue_cagr(metrics)
    margin_change = float(latest["ebit_margin"] - metrics["ebit_margin"].iloc[0])
    fcf_change = float(latest["free_cash_flow"] - metrics["free_cash_flow"].iloc[0])
    return {
        "revenue_cagr": cagr,
        "latest_ebit_margin": float(latest["ebit_margin"]),
        "latest_net_margin": float(latest["net_margin"]),
        "latest_fcf_margin": float(latest["fcf_margin"]),
        "latest_fcf_conversion": float(latest["fcf_conversion"]),
        "latest_debt_to_fcf": float(latest["debt_to_fcf"]),
        "ebit_margin_change": margin_change,
        "fcf_change": fcf_change,
        "revenue_trend": "growing" if cagr > 0 else "declining",
        "margin_trend": "expanding" if margin_change > 0 else "contracting",
        "fcf_trend": "improving" if fcf_change > 0 else "weakening",
    }

