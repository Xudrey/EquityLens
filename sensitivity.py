"""DCF sensitivity table helpers."""

from dataclasses import replace
import pandas as pd
from .config import DCFAssumptions
from .dcf import run_dcf


def wacc_terminal_growth_sensitivity(data: pd.DataFrame, assumptions: DCFAssumptions) -> pd.DataFrame:
    """Fair value per share across WACC and terminal-growth cases."""
    wacc_values = [0.075, 0.08, 0.085, 0.09, 0.095]
    growth_values = [0.015, 0.02, 0.025, 0.03, 0.035]
    return pd.DataFrame(
        [[run_dcf(data, replace(assumptions, wacc=wacc, terminal_growth=g))["fair_value_per_share"] for g in growth_values] for wacc in wacc_values],
        index=pd.Index(wacc_values, name="WACC"),
        columns=pd.Index(growth_values, name="Terminal Growth"),
    )


def revenue_margin_sensitivity(data: pd.DataFrame, assumptions: DCFAssumptions) -> pd.DataFrame:
    """Fair value per share across revenue-growth and EBIT-margin cases."""
    growth_values = [0.045, 0.055, 0.065, 0.075, 0.085]
    margin_values = [0.255, 0.265, 0.275, 0.285, 0.295]
    return pd.DataFrame(
        [[run_dcf(data, replace(assumptions, revenue_growth=g, ebit_margin=m))["fair_value_per_share"] for m in margin_values] for g in growth_values],
        index=pd.Index(growth_values, name="Revenue Growth"),
        columns=pd.Index(margin_values, name="EBIT Margin"),
    )
