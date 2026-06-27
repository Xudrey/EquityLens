"""DCF sensitivity analysis helpers."""

from dataclasses import replace

import pandas as pd

from .config import DCFAssumptions
from .dcf import run_dcf


def wacc_terminal_growth_sensitivity(
    data: pd.DataFrame,
    assumptions: DCFAssumptions,
    wacc_values: list[float] | None = None,
    terminal_growth_values: list[float] | None = None,
) -> pd.DataFrame:
    """Return fair value per share across WACC and terminal growth cases."""
    wacc_values = wacc_values or [0.075, 0.08, 0.085, 0.09, 0.095]
    terminal_growth_values = terminal_growth_values or [0.015, 0.02, 0.025, 0.03, 0.035]
    return pd.DataFrame(
        [
            [
                run_dcf(data, replace(assumptions, wacc=wacc, terminal_growth=growth))[
                    "fair_value_per_share"
                ]
                for growth in terminal_growth_values
            ]
            for wacc in wacc_values
        ],
        index=pd.Index(wacc_values, name="WACC"),
        columns=pd.Index(terminal_growth_values, name="Terminal Growth"),
    )


def revenue_margin_sensitivity(
    data: pd.DataFrame,
    assumptions: DCFAssumptions,
    revenue_growth_values: list[float] | None = None,
    ebit_margin_values: list[float] | None = None,
) -> pd.DataFrame:
    """Return fair value per share across revenue growth and EBIT margin cases."""
    revenue_growth_values = revenue_growth_values or [0.045, 0.055, 0.065, 0.075, 0.085]
    ebit_margin_values = ebit_margin_values or [0.255, 0.265, 0.275, 0.285, 0.295]
    return pd.DataFrame(
        [
            [
                run_dcf(
                    data,
                    replace(assumptions, revenue_growth=growth, ebit_margin=margin),
                )["fair_value_per_share"]
                for margin in ebit_margin_values
            ]
            for growth in revenue_growth_values
        ],
        index=pd.Index(revenue_growth_values, name="Revenue Growth"),
        columns=pd.Index(ebit_margin_values, name="EBIT Margin"),
    )

