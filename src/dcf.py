"""Simple, explainable five-year discounted cash flow valuation."""

from dataclasses import asdict
from typing import Any

import pandas as pd

from .config import DCFAssumptions


def run_dcf(
    historical_data: pd.DataFrame,
    assumptions: DCFAssumptions,
) -> dict[str, Any]:
    """Project unlevered FCF and calculate enterprise and equity value."""
    if assumptions.wacc <= assumptions.terminal_growth:
        raise ValueError("WACC must be greater than terminal growth.")
    if assumptions.forecast_years < 1:
        raise ValueError("Forecast period must be at least one year.")

    latest = historical_data.iloc[-1]
    previous_revenue = float(latest["revenue"])
    rows: list[dict[str, float | int]] = []

    for period in range(1, assumptions.forecast_years + 1):
        revenue = previous_revenue * (1 + assumptions.revenue_growth)
        ebit = revenue * assumptions.ebit_margin
        taxes = ebit * assumptions.tax_rate
        nopat = ebit - taxes
        da = revenue * assumptions.da_pct_revenue
        capex = revenue * assumptions.capex_pct_revenue
        change_nwc = (revenue - previous_revenue) * assumptions.nwc_pct_revenue
        unlevered_fcf = nopat + da - capex - change_nwc
        discount_factor = 1 / (1 + assumptions.wacc) ** period
        pv_fcf = unlevered_fcf * discount_factor
        rows.append(
            {
                "year": int(latest["year"]) + period,
                "revenue": revenue,
                "ebit": ebit,
                "taxes": taxes,
                "nopat": nopat,
                "d_and_a": da,
                "capex": capex,
                "change_nwc": change_nwc,
                "unlevered_fcf": unlevered_fcf,
                "discount_factor": discount_factor,
                "pv_fcf": pv_fcf,
            }
        )
        previous_revenue = revenue

    projections = pd.DataFrame(rows)
    terminal_fcf = float(projections["unlevered_fcf"].iloc[-1]) * (
        1 + assumptions.terminal_growth
    )
    terminal_value = terminal_fcf / (assumptions.wacc - assumptions.terminal_growth)
    pv_terminal_value = terminal_value * float(projections["discount_factor"].iloc[-1])
    pv_forecast_fcf = float(projections["pv_fcf"].sum())
    enterprise_value = pv_forecast_fcf + pv_terminal_value
    equity_value = enterprise_value + float(latest["cash"]) - float(latest["total_debt"])
    fair_value_per_share = equity_value / float(latest["diluted_shares"])
    current_price = float(latest["current_share_price"])
    upside_downside = fair_value_per_share / current_price - 1

    return {
        "assumptions": asdict(assumptions),
        "projections": projections,
        "pv_forecast_fcf": pv_forecast_fcf,
        "terminal_value": terminal_value,
        "pv_terminal_value": pv_terminal_value,
        "enterprise_value": enterprise_value,
        "cash": float(latest["cash"]),
        "debt": float(latest["total_debt"]),
        "equity_value": equity_value,
        "diluted_shares": float(latest["diluted_shares"]),
        "fair_value_per_share": fair_value_per_share,
        "current_share_price": current_price,
        "upside_downside": upside_downside,
    }

