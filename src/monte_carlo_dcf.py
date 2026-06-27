"""Python-native Monte Carlo DCF valuation helpers.

The simulation layer sits on top of the base DCF workflow. It does not replace
base-case valuation; it shows how uncertainty in key assumptions can change
fair value per share, and it documents the value drivers, distributions, and
constraints behind each run.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from .config import DCFAssumptions
from .dcf import run_dcf
from .financial_analysis import calculate_financial_metrics


@dataclass(frozen=True)
class DistributionSpec:
    """Describe a supported probability distribution for one assumption."""

    distribution_type: str
    mean: float | None = None
    stdev: float | None = None
    low: float | None = None
    mode: float | None = None
    high: float | None = None
    reason: str = ""
    data_source: str = "Analyst judgment"

    def parameters(self) -> dict[str, float]:
        """Return only populated numeric distribution parameters."""
        return {
            key: value
            for key, value in {
                "mean": self.mean,
                "stdev": self.stdev,
                "low": self.low,
                "mode": self.mode,
                "high": self.high,
            }.items()
            if value is not None
        }


NASDAQ_DEFAULT_DISTRIBUTIONS: dict[str, DistributionSpec] = {
    "revenue_growth": DistributionSpec(
        "triangular",
        low=0.03,
        mode=0.06,
        high=0.09,
        reason="Revenue growth can be framed as conservative, base, and optimistic business scenarios.",
    ),
    "ebit_margin": DistributionSpec(
        "triangular",
        low=0.25,
        mode=0.30,
        high=0.35,
        reason="Operating margin has a base case but can vary with operating leverage, integration costs, competition, and business mix.",
    ),
    "tax_rate": DistributionSpec(
        "triangular",
        low=0.18,
        mode=0.22,
        high=0.26,
        reason="Tax rate can fluctuate, but a normalized range is more useful than an unbounded draw.",
    ),
    "fcf_margin": DistributionSpec(
        "triangular",
        low=0.18,
        mode=0.23,
        high=0.28,
        reason="Free cash flow margin depends on profitability, capex, working capital, and cash conversion.",
    ),
    "wacc": DistributionSpec(
        "triangular",
        low=0.075,
        mode=0.09,
        high=0.105,
        reason="WACC depends on interest rates, equity risk premium, leverage, and market conditions.",
    ),
    "terminal_growth": DistributionSpec(
        "triangular",
        low=0.015,
        mode=0.025,
        high=0.035,
        reason="Terminal growth should represent mature long-term growth and remain below discount-rate assumptions.",
    ),
}


DRIVER_EXPLANATIONS: dict[str, str] = {
    "revenue_growth": "Revenue growth drives the scale of future cash flows and captures market activity, recurring data/index demand, and financial-technology growth.",
    "ebit_margin": "EBIT margin captures operating leverage, integration execution, competition, pricing pressure, and business mix.",
    "fcf_margin": "FCF margin converts revenue into distributable cash flow after operating, capex, and working-capital needs.",
    "wacc": "WACC discounts future cash flows and reflects interest rates, equity risk premium, leverage, and company-specific risk.",
    "terminal_growth": "Terminal growth controls the continuing value after the explicit forecast period and must stay conservative.",
    "tax_rate": "Tax rate affects NOPAT and can move with geography, regulation, tax planning, and one-time items.",
    "net_debt": "Net debt reduces equity value after enterprise value is calculated and highlights leverage risk.",
    "diluted_shares": "Diluted shares determine how much equity value belongs to each share; dilution lowers fair value per share.",
}


@dataclass(frozen=True)
class MonteCarloDCFInputs:
    """Required inputs for a reusable Monte Carlo DCF run."""

    ticker: str
    company_name: str
    latest_revenue: float
    current_price: float
    cash: float
    debt: float
    diluted_shares: float
    forecast_years: int = 5
    simulations: int = 10_000
    random_seed: int | None = 42
    base_revenue_growth: float = 0.06
    base_ebit_margin: float = 0.30
    base_tax_rate: float = 0.22
    base_fcf_margin: float | None = 0.23
    base_fcf_conversion: float | None = None
    base_wacc: float = 0.09
    base_terminal_growth: float = 0.025
    base_case_fair_value: float | None = None
    distributions: dict[str, DistributionSpec] = field(
        default_factory=lambda: NASDAQ_DEFAULT_DISTRIBUTIONS.copy()
    )
    historical_financials: pd.DataFrame | None = None
    base_assumptions: DCFAssumptions | None = None


@dataclass(frozen=True)
class MonteCarloDCFResult:
    """Structured Monte Carlo output for Streamlit, Excel, and memo text."""

    simulation_df: pd.DataFrame
    summary: dict[str, Any]
    sensitivity: pd.DataFrame
    value_driver_table: pd.DataFrame
    explanation: str

    def __iter__(self):
        """Allow legacy unpacking as simulation_df, summary, sensitivity."""
        yield self.simulation_df
        yield self.summary
        yield self.sensitivity


def sample_distribution(
    spec: DistributionSpec,
    rng: np.random.Generator,
    size: int = 1,
) -> np.ndarray:
    """Sample from a supported distribution specification."""
    distribution_type = spec.distribution_type.lower().strip()
    if distribution_type == "normal":
        if spec.mean is None or spec.stdev is None:
            raise ValueError("Normal distribution requires mean and stdev.")
        return rng.normal(spec.mean, spec.stdev, size=size)
    if distribution_type == "triangular":
        if spec.low is None or spec.mode is None or spec.high is None:
            raise ValueError("Triangular distribution requires low, mode, and high.")
        if not spec.low <= spec.mode <= spec.high:
            raise ValueError("Triangular distribution requires low <= mode <= high.")
        return rng.triangular(spec.low, spec.mode, spec.high, size=size)
    if distribution_type == "uniform":
        if spec.low is None or spec.high is None:
            raise ValueError("Uniform distribution requires low and high.")
        if spec.low > spec.high:
            raise ValueError("Uniform distribution requires low <= high.")
        return rng.uniform(spec.low, spec.high, size=size)
    raise ValueError(f"Unsupported distribution type: {spec.distribution_type}")


def _draw_assumption(
    inputs: MonteCarloDCFInputs,
    name: str,
    base_value: float | None,
    rng: np.random.Generator,
) -> float:
    """Draw an assumption or use its base case when no distribution is supplied."""
    spec = inputs.distributions.get(name)
    if spec is None:
        if base_value is None:
            raise ValueError(f"No distribution or base value was provided for {name}.")
        return float(base_value)
    return float(sample_distribution(spec, rng, size=1)[0])


def _historical_average_and_volatility(
    series: pd.Series) -> tuple[float | None, float | None]:
    """Return average and sample volatility for usable historical observations."""
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return None, None
    average = float(clean.mean())
    volatility = float(clean.std(ddof=1)) if len(clean) > 1 else None
    return average, volatility


def _constraint_note(existing: list[str], note: str) -> None:
    """Append a note only once so constraint output stays readable."""
    if note not in existing:
        existing.append(note)


def apply_simulation_constraints(
    assumptions: dict[str, float],
    inputs: MonteCarloDCFInputs,
    *,
    allow_fcf_above_ebit_margin: bool = False,
) -> tuple[dict[str, float], str]:
    """Apply simple valuation and operating guardrails to assumption draws.

    The MVP uses transparent rule-based adjustments. A correlation matrix can be
    added later without changing the output contract.
    """
    constrained = assumptions.copy()
    notes: list[str] = []

    original_growth = constrained["revenue_growth"]
    constrained["revenue_growth"] = float(np.clip(original_growth, -0.10, 0.25))
    if constrained["revenue_growth"] != original_growth:
        _constraint_note(notes, "Revenue growth clipped to the -10% to 25% guardrail.")

    original_ebit = constrained["ebit_margin"]
    constrained["ebit_margin"] = float(np.clip(original_ebit, 0.0, 0.60))
    if constrained["ebit_margin"] != original_ebit:
        _constraint_note(notes, "EBIT margin clipped to the 0% to 60% guardrail.")

    original_tax = constrained["tax_rate"]
    constrained["tax_rate"] = float(np.clip(original_tax, 0.0, 0.35))
    if constrained["tax_rate"] != original_tax:
        _constraint_note(notes, "Tax rate clipped to the 0% to 35% guardrail.")

    if "fcf_margin" in constrained:
        original_fcf = constrained["fcf_margin"]
        constrained["fcf_margin"] = float(np.clip(original_fcf, 0.0, 0.60))
        if constrained["fcf_margin"] != original_fcf:
            _constraint_note(notes, "FCF margin clipped to the 0% to 60% guardrail.")
        if not allow_fcf_above_ebit_margin and constrained["fcf_margin"] > constrained["ebit_margin"]:
            constrained["fcf_margin"] = constrained["ebit_margin"]
            _constraint_note(notes, "FCF margin capped at EBIT margin to avoid unrealistic cash conversion.")

    if "fcf_conversion" in constrained:
        original_conversion = constrained["fcf_conversion"]
        constrained["fcf_conversion"] = float(np.clip(original_conversion, 0.0, 2.0))
        if constrained["fcf_conversion"] != original_conversion:
            _constraint_note(notes, "FCF conversion clipped to the 0.0x to 2.0x guardrail.")

    if constrained["revenue_growth"] < 0.03 and constrained["ebit_margin"] > inputs.base_ebit_margin:
        constrained["ebit_margin"] = float(inputs.base_ebit_margin)
        _constraint_note(notes, "Weak revenue growth capped EBIT margin at the base margin.")

    if constrained["revenue_growth"] > 0.09 and constrained["wacc"] < inputs.base_wacc:
        constrained["wacc"] = float(inputs.base_wacc)
        _constraint_note(notes, "High growth scenario prevented WACC from falling below the base WACC.")

    if "fcf_margin" in constrained and constrained["ebit_margin"] < inputs.base_ebit_margin - 0.03:
        max_fcf_margin = max(0.0, constrained["ebit_margin"] - 0.01)
        if constrained["fcf_margin"] > max_fcf_margin:
            constrained["fcf_margin"] = max_fcf_margin
            _constraint_note(notes, "Margin compression scenario reduced FCF margin.")

    original_terminal = constrained["terminal_growth"]
    constrained["terminal_growth"] = float(np.clip(original_terminal, -0.01, 0.04))
    if constrained["terminal_growth"] != original_terminal:
        _constraint_note(notes, "Terminal growth clipped to the -1% to 4% guardrail.")

    if constrained["revenue_growth"] > 0 and constrained["terminal_growth"] > constrained["revenue_growth"]:
        constrained["terminal_growth"] = max(constrained["revenue_growth"] - 0.005, 0.0)
        _constraint_note(notes, "Terminal growth constrained below forecast revenue growth.")

    minimum_wacc = constrained["terminal_growth"] + 0.01
    if constrained["wacc"] < minimum_wacc:
        constrained["wacc"] = minimum_wacc
        _constraint_note(notes, "WACC increased to stay at least 1 percentage point above terminal growth.")

    return constrained, "; ".join(notes) if notes else "None"


# Backward-compatible alias for earlier code/tests that referenced the private helper.
def _constrain_assumptions(assumptions: dict[str, float]) -> dict[str, float]:
    """Apply generic guardrails without company-specific base-input context."""
    shim_inputs = MonteCarloDCFInputs(
        ticker="N/A",
        company_name="N/A",
        latest_revenue=1,
        current_price=1,
        cash=0,
        debt=0,
        diluted_shares=1,
        base_revenue_growth=float(assumptions.get("revenue_growth", 0.06)),
        base_ebit_margin=float(assumptions.get("ebit_margin", 0.30)),
        base_tax_rate=float(assumptions.get("tax_rate", 0.22)),
        base_fcf_margin=assumptions.get("fcf_margin"),
        base_wacc=float(assumptions.get("wacc", 0.09)),
        base_terminal_growth=float(assumptions.get("terminal_growth", 0.025)),
    )
    constrained, _ = apply_simulation_constraints(assumptions, shim_inputs)
    return constrained


def validate_monte_carlo_inputs(inputs: MonteCarloDCFInputs) -> None:
    """Raise a clear error when core inputs cannot support a valuation."""
    if inputs.latest_revenue <= 0:
        raise ValueError("Latest revenue must be positive.")
    if inputs.current_price <= 0:
        raise ValueError("Current price must be positive.")
    if inputs.diluted_shares <= 0:
        raise ValueError("Diluted shares must be positive.")
    if inputs.forecast_years < 1:
        raise ValueError("Forecast years must be at least 1.")
    if inputs.simulations < 1:
        raise ValueError("Simulations must be at least 1.")
    if inputs.base_fcf_margin is None and inputs.base_fcf_conversion is None:
        raise ValueError("Provide either base_fcf_margin or base_fcf_conversion.")


def run_single_dcf_simulation(
    inputs: MonteCarloDCFInputs,
    assumptions: dict[str, float],
) -> dict[str, float | bool | str]:
    """Run one simulated DCF and return valuation outputs."""
    constrained, constraint_notes = apply_simulation_constraints(assumptions, inputs)
    revenue = float(inputs.latest_revenue)
    forecast_fcfs: list[float] = []
    discount_factors: list[float] = []

    for year_number in range(1, inputs.forecast_years + 1):
        revenue *= 1 + constrained["revenue_growth"]
        ebit = revenue * constrained["ebit_margin"]
        nopat = ebit * (1 - constrained["tax_rate"])
        if "fcf_margin" in constrained:
            fcf = revenue * constrained["fcf_margin"]
        else:
            fcf = nopat * constrained["fcf_conversion"]
        discount_factor = 1 / (1 + constrained["wacc"]) ** year_number
        forecast_fcfs.append(fcf)
        discount_factors.append(discount_factor)

    terminal_value = (
        forecast_fcfs[-1]
        * (1 + constrained["terminal_growth"])
        / (constrained["wacc"] - constrained["terminal_growth"])
    )
    pv_forecast_fcf = float(np.dot(forecast_fcfs, discount_factors))
    pv_terminal_value = terminal_value * discount_factors[-1]
    enterprise_value = pv_forecast_fcf + pv_terminal_value
    equity_value = enterprise_value + float(inputs.cash) - float(inputs.debt)
    invalid_simulation_flag = equity_value < 0
    fair_value_per_share = max(equity_value, 0) / float(inputs.diluted_shares)
    implied_upside_downside = fair_value_per_share / float(inputs.current_price) - 1
    if invalid_simulation_flag:
        constraint_notes = (
            constraint_notes + "; " if constraint_notes != "None" else ""
        ) + "Negative equity value set fair value per share to zero."

    return {
        **constrained,
        "final_year_revenue": revenue,
        "final_year_fcf": forecast_fcfs[-1],
        "pv_forecast_fcf": pv_forecast_fcf,
        "terminal_value": terminal_value,
        "pv_terminal_value": pv_terminal_value,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "fair_value_per_share": fair_value_per_share,
        "implied_upside_downside": implied_upside_downside,
        "invalid_simulation_flag": invalid_simulation_flag,
        "valid_simulation": not invalid_simulation_flag,
        "constraint_notes": constraint_notes,
    }


def _sensitivity_impact_score(
    financials: pd.DataFrame,
    assumptions: DCFAssumptions,
    driver: str,
) -> float:
    """Estimate valuation impact from a small one-variable perturbation."""
    financials = financials.copy()
    for column in [
        "revenue",
        "ebit",
        "net_income",
        "free_cash_flow",
        "cash",
        "total_debt",
        "diluted_shares",
        "current_share_price",
    ]:
        if column in financials.columns:
            financials[column] = pd.to_numeric(financials[column], errors="coerce").astype(float)
    base_result = run_dcf(financials, assumptions)
    base_value = float(base_result["fair_value_per_share"])
    if base_value <= 0:
        return 0.0

    high_data = financials.copy()
    low_data = financials.copy()
    try:
        if driver == "revenue_growth":
            high = run_dcf(high_data, replace(assumptions, revenue_growth=assumptions.revenue_growth + 0.01))["fair_value_per_share"]
            low = run_dcf(low_data, replace(assumptions, revenue_growth=max(assumptions.revenue_growth - 0.01, -0.10)))["fair_value_per_share"]
        elif driver == "ebit_margin":
            high = run_dcf(high_data, replace(assumptions, ebit_margin=assumptions.ebit_margin + 0.01))["fair_value_per_share"]
            low = run_dcf(low_data, replace(assumptions, ebit_margin=max(assumptions.ebit_margin - 0.01, 0.0)))["fair_value_per_share"]
        elif driver == "tax_rate":
            high = run_dcf(high_data, replace(assumptions, tax_rate=min(assumptions.tax_rate + 0.01, 0.35)))["fair_value_per_share"]
            low = run_dcf(low_data, replace(assumptions, tax_rate=max(assumptions.tax_rate - 0.01, 0.0)))["fair_value_per_share"]
        elif driver == "wacc":
            high = run_dcf(high_data, replace(assumptions, wacc=assumptions.wacc + 0.01))["fair_value_per_share"]
            low_wacc = max(assumptions.wacc - 0.01, assumptions.terminal_growth + 0.01)
            low = run_dcf(low_data, replace(assumptions, wacc=low_wacc))["fair_value_per_share"]
        elif driver == "terminal_growth":
            high_growth = min(assumptions.terminal_growth + 0.005, assumptions.wacc - 0.01, 0.04)
            high = run_dcf(high_data, replace(assumptions, terminal_growth=high_growth))["fair_value_per_share"]
            low = run_dcf(low_data, replace(assumptions, terminal_growth=max(assumptions.terminal_growth - 0.005, -0.01)))["fair_value_per_share"]
        elif driver == "net_debt":
            latest_index = high_data.index[-1]
            high_data.loc[latest_index, "total_debt"] = high_data.loc[latest_index, "total_debt"] * 1.10
            low_data.loc[latest_index, "total_debt"] = low_data.loc[latest_index, "total_debt"] * 0.90
            high = run_dcf(high_data, assumptions)["fair_value_per_share"]
            low = run_dcf(low_data, assumptions)["fair_value_per_share"]
        elif driver == "diluted_shares":
            latest_index = high_data.index[-1]
            high_data.loc[latest_index, "diluted_shares"] = high_data.loc[latest_index, "diluted_shares"] * 1.05
            low_data.loc[latest_index, "diluted_shares"] = low_data.loc[latest_index, "diluted_shares"] * 0.95
            high = run_dcf(high_data, assumptions)["fair_value_per_share"]
            low = run_dcf(low_data, assumptions)["fair_value_per_share"]
        elif driver == "fcf_margin":
            # Base DCF does not directly use FCF margin. Approximate impact by moving capex/revenue.
            high = run_dcf(high_data, replace(assumptions, capex_pct_revenue=max(assumptions.capex_pct_revenue - 0.01, 0.0)))["fair_value_per_share"]
            low = run_dcf(low_data, replace(assumptions, capex_pct_revenue=assumptions.capex_pct_revenue + 0.01))["fair_value_per_share"]
        else:
            return 0.0
    except ValueError:
        return 0.0
    return float(abs(high - low) / base_value)


def identify_value_drivers(
    historical_financials: pd.DataFrame,
    base_assumptions: DCFAssumptions,
) -> pd.DataFrame:
    """Rank value drivers by valuation impact and uncertainty.

    Impact is estimated through simple sensitivity analysis. Uncertainty uses
    historical volatility when available plus business-logic overlays for Nasdaq.
    """
    data = historical_financials.sort_values("year").copy()
    latest = data.iloc[-1]
    metrics = calculate_financial_metrics(data)
    driver_inputs = {
        "revenue_growth": (base_assumptions.revenue_growth, metrics.get("revenue_growth", pd.Series(dtype=float))),
        "ebit_margin": (base_assumptions.ebit_margin, metrics.get("ebit_margin", pd.Series(dtype=float))),
        "fcf_margin": (float(latest["free_cash_flow"]) / float(latest["revenue"]), metrics.get("fcf_margin", pd.Series(dtype=float))),
        "wacc": (base_assumptions.wacc, pd.Series(dtype=float)),
        "terminal_growth": (base_assumptions.terminal_growth, pd.Series(dtype=float)),
        "tax_rate": (base_assumptions.tax_rate, pd.Series(dtype=float)),
        "net_debt": (float(latest["total_debt"]) - float(latest["cash"]), data["total_debt"] - data["cash"]),
        "diluted_shares": (float(latest["diluted_shares"]), data["diluted_shares"]),
    }
    uncertainty_overlays = {
        "revenue_growth": 0.70,
        "ebit_margin": 0.65,
        "fcf_margin": 0.70,
        "wacc": 0.80,
        "terminal_growth": 0.75,
        "tax_rate": 0.45,
        "net_debt": 0.70,
        "diluted_shares": 0.35,
    }
    rows = []
    for driver, (base_value, history) in driver_inputs.items():
        historical_average, historical_volatility = _historical_average_and_volatility(history)
        impact_score = _sensitivity_impact_score(data, base_assumptions, driver)
        if historical_volatility is None:
            uncertainty_score = uncertainty_overlays[driver]
        else:
            denominator = abs(historical_average) if historical_average not in (None, 0) else 1.0
            coefficient_of_variation = min(abs(historical_volatility / denominator), 1.0)
            uncertainty_score = float(min(1.0, 0.5 * coefficient_of_variation + 0.5 * uncertainty_overlays[driver]))
        final_score = impact_score * 0.65 + uncertainty_score * 0.35
        rows.append(
            {
                "value_driver": driver,
                "base_value": float(base_value),
                "historical_average": historical_average,
                "historical_volatility": historical_volatility,
                "valuation_impact_score": impact_score,
                "uncertainty_score": uncertainty_score,
                "final_priority_score": final_score,
                "explanation": DRIVER_EXPLANATIONS[driver],
            }
        )
    return pd.DataFrame(rows).sort_values("final_priority_score", ascending=False).reset_index(drop=True)


def _distribution_parameter_text(spec: DistributionSpec) -> str:
    """Format distribution parameters for tables and explanations."""
    params = spec.parameters()
    return ", ".join(f"{key}={value:.2%}" for key, value in params.items())


def explain_distribution_choices(
    distributions: dict[str, DistributionSpec],
    value_driver_table: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Explain why each value-driver distribution was selected."""
    rows = []
    for driver, spec in distributions.items():
        distribution = spec.distribution_type.lower().strip()
        if distribution == "triangular":
            why_distribution = (
                "Triangular is appropriate because the model has a conservative, base, and optimistic scenario rather than a precise statistical mean."
            )
            parameter_meaning = "Low is the bear case, mode is the most likely/base case, and high is the bull case."
        elif distribution == "normal":
            why_distribution = "Normal is appropriate when historical observations are stable and centered around an average."
            parameter_meaning = "Mean is the center of the draw and stdev controls dispersion around that center."
        elif distribution == "uniform":
            why_distribution = "Uniform is appropriate when only a reasonable range is known and no most-likely case is confident enough."
            parameter_meaning = "Low and high define the range; every value in the range receives equal weight."
        else:
            why_distribution = "Unsupported distribution type; review configuration."
            parameter_meaning = "Review parameters."
        rows.append(
            {
                "value_driver": driver,
                "distribution": distribution,
                "parameters": _distribution_parameter_text(spec),
                "data_source": spec.data_source,
                "why_this_driver_matters": DRIVER_EXPLANATIONS.get(driver, "This assumption affects projected valuation outcomes."),
                "why_this_distribution": spec.reason or why_distribution,
                "parameter_meaning": parameter_meaning,
                "business_risk_represented": DRIVER_EXPLANATIONS.get(driver, "Forecast uncertainty."),
                "basis": spec.data_source,
            }
        )
    explanation_df = pd.DataFrame(rows)
    if value_driver_table is not None and not value_driver_table.empty:
        ranking = value_driver_table[
            ["value_driver", "valuation_impact_score", "uncertainty_score", "final_priority_score"]
        ]
        explanation_df = explanation_df.merge(ranking, on="value_driver", how="left")
    return explanation_df


def calculate_assumption_sensitivity(simulation_df: pd.DataFrame) -> pd.DataFrame:
    """Measure simple Pearson correlations between assumptions and fair value."""
    assumption_columns = [
        "revenue_growth",
        "ebit_margin",
        "tax_rate",
        "fcf_margin",
        "fcf_conversion",
        "wacc",
        "terminal_growth",
    ]
    available_columns = [
        column for column in assumption_columns if column in simulation_df.columns
    ]
    rows = []
    for column in available_columns:
        series = pd.to_numeric(simulation_df[column], errors="coerce")
        values = pd.to_numeric(simulation_df["fair_value_per_share"], errors="coerce")
        if series.nunique(dropna=True) <= 1:
            correlation = np.nan
        else:
            correlation = float(series.corr(values))
        rows.append(
            {
                "assumption": column,
                "correlation_with_fair_value": correlation,
                "absolute_correlation": abs(correlation) if pd.notna(correlation) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(
        "absolute_correlation", ascending=False, na_position="last"
    )


def summarize_monte_carlo_results(
    simulation_df: pd.DataFrame,
    inputs: MonteCarloDCFInputs,
    value_driver_table: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Summarize the simulated valuation distribution."""
    fair_values = pd.to_numeric(simulation_df["fair_value_per_share"], errors="coerce")
    valid_values = fair_values.dropna()
    median_value = float(valid_values.median())
    percentile_5 = float(valid_values.quantile(0.05))
    percentile_95 = float(valid_values.quantile(0.95))
    probability_above = float((valid_values > inputs.current_price).mean())
    range_width = percentile_95 - percentile_5
    relative_width = range_width / max(median_value, 0.01)
    if relative_width < 0.50:
        confidence_note = "Narrow simulated range; assumptions are producing a relatively tight valuation band."
    elif relative_width < 1.00:
        confidence_note = "Moderate simulated range; valuation is meaningfully sensitive to the selected assumptions."
    else:
        confidence_note = "Wide simulated range; valuation confidence is low and assumptions should be reviewed carefully."

    if probability_above > 0.65:
        probability_context = "The valuation distribution leans positive versus the current market price."
    elif probability_above < 0.35:
        probability_context = "The valuation distribution leans negative versus the current market price."
    else:
        probability_context = "The valuation distribution is mixed versus the current market price."

    median_upside = (median_value - inputs.current_price) / inputs.current_price
    if median_upside >= 0.15:
        valuation_label = "Undervalued"
    elif median_upside <= -0.15:
        valuation_label = "Overvalued"
    else:
        valuation_label = "Fairly Valued"

    sensitivity = calculate_assumption_sensitivity(simulation_df)
    positive_drivers = sensitivity[sensitivity["correlation_with_fair_value"] > 0]
    risk_drivers = sensitivity[sensitivity["correlation_with_fair_value"] < 0]
    top_positive = positive_drivers.head(3)["assumption"].tolist()
    top_risks = risk_drivers.head(3)["assumption"].tolist()
    if value_driver_table is not None and not value_driver_table.empty:
        priority_drivers = value_driver_table.head(3)["value_driver"].tolist()
    else:
        priority_drivers = sensitivity.head(3)["assumption"].tolist()

    return {
        "ticker": inputs.ticker,
        "company_name": inputs.company_name,
        "simulations_run": int(len(simulation_df)),
        "valid_simulations": int((~simulation_df["invalid_simulation_flag"]).sum()),
        "invalid_simulations": int(simulation_df["invalid_simulation_flag"].sum()),
        "current_price": float(inputs.current_price),
        "mean_fair_value": float(valid_values.mean()),
        "median_fair_value": median_value,
        "percentile_5": percentile_5,
        "percentile_10": float(valid_values.quantile(0.10)),
        "percentile_25": float(valid_values.quantile(0.25)),
        "percentile_75": float(valid_values.quantile(0.75)),
        "percentile_90": float(valid_values.quantile(0.90)),
        "percentile_95": percentile_95,
        "probability_above_current_price": probability_above,
        "probability_below_current_price": float((valid_values < inputs.current_price).mean()),
        "median_implied_upside_downside": median_upside,
        "base_case_fair_value": inputs.base_case_fair_value,
        "valuation_label": valuation_label,
        "confidence_note": confidence_note,
        "probability_context": probability_context,
        "top_3_positive_value_drivers": ", ".join(top_positive) if top_positive else "None identified",
        "top_3_risk_drivers": ", ".join(top_risks) if top_risks else "None identified",
        "top_3_priority_value_drivers": ", ".join(priority_drivers),
    }


def generate_monte_carlo_explanation(
    summary: dict[str, Any],
    value_driver_table: pd.DataFrame,
    distribution_table: pd.DataFrame,
) -> str:
    """Generate a plain-English explanation of the simulation setup and output."""
    top_drivers = ", ".join(value_driver_table.head(3)["value_driver"].tolist())
    distribution_names = ", ".join(
        f"{row.value_driver}: {row.distribution}"
        for row in distribution_table.itertuples(index=False)
    )
    base_case_value = summary.get("base_case_fair_value")
    base_case_phrase = (
        f"the base-case DCF fair value of ${base_case_value:.2f} per share"
        if base_case_value is not None and pd.notna(base_case_value)
        else "the current base-case DCF setup"
    )
    return (
        f"The Monte Carlo simulation tests how uncertainty in key DCF assumptions changes the estimated fair value for {summary['ticker']}. "
        f"It starts with {base_case_phrase}, then runs {summary['simulations_run']:,} valuation cases using independent Python/numpy draws. "
        f"The highest-priority value drivers are {top_drivers}. Distributions used were {distribution_names}. "
        "The MVP applies transparent constraints: WACC must exceed terminal growth by at least 1 percentage point, terminal growth is capped at 4%, revenue growth and margins are clipped to realistic ranges, FCF margin is capped at EBIT margin, and negative equity values are flagged with fair value per share set to zero. "
        f"The median simulated fair value is ${summary['median_fair_value']:.2f}, implying {summary['median_implied_upside_downside']:.1%} median upside/downside versus the current price of ${summary['current_price']:.2f}. "
        f"This produces a {summary['valuation_label']} simulation label. {summary['probability_context']} {summary['confidence_note']}"
    )


def create_value_driver_table(
    value_driver_ranking: pd.DataFrame,
    distribution_table: pd.DataFrame,
) -> pd.DataFrame:
    """Combine ranking and distribution explanations into one exportable table."""
    table = distribution_table.merge(
        value_driver_ranking[
            [
                "value_driver",
                "base_value",
                "historical_average",
                "historical_volatility",
                "valuation_impact_score",
                "uncertainty_score",
                "final_priority_score",
            ]
        ],
        on="value_driver",
        how="outer",
        suffixes=("", "_ranking"),
    )
    for column in ["valuation_impact_score", "uncertainty_score", "final_priority_score"]:
        ranking_column = f"{column}_ranking"
        if ranking_column in table.columns:
            table[column] = table[column].fillna(table[ranking_column])
            table = table.drop(columns=[ranking_column])
    table["constraint_applied"] = table["value_driver"].map(
        {
            "revenue_growth": "Clipped to -10% to 25%; weak growth limits margin expansion.",
            "ebit_margin": "Clipped to 0% to 60%; weak growth can cap margin expansion.",
            "fcf_margin": "Clipped to 0% to 60%; capped at EBIT margin unless overridden.",
            "wacc": "Must remain at least 1 percentage point above terminal growth; high growth prevents low WACC.",
            "terminal_growth": "Capped at 4%, below WACC, and generally below forecast revenue growth.",
            "tax_rate": "Clipped to 0% to 35%.",
            "net_debt": "Held constant in MVP unless explicitly simulated later.",
            "diluted_shares": "Held constant in MVP unless explicitly simulated later.",
        }
    ).fillna("No specific constraint beyond model validation.")
    ordered_columns = [
        "value_driver",
        "distribution",
        "parameters",
        "data_source",
        "why_this_driver_matters",
        "why_this_distribution",
        "constraint_applied",
        "valuation_impact_score",
        "uncertainty_score",
        "final_priority_score",
        "base_value",
        "historical_average",
        "historical_volatility",
        "parameter_meaning",
        "business_risk_represented",
        "basis",
    ]
    return table[[column for column in ordered_columns if column in table.columns]].sort_values(
        "final_priority_score", ascending=False, na_position="last"
    ).reset_index(drop=True)


def create_histogram_data(
    simulation_df: pd.DataFrame,
    bins: int = 30,
) -> pd.DataFrame:
    """Return histogram-ready bin data for Streamlit, Altair, or Excel."""
    fair_values = pd.to_numeric(simulation_df["fair_value_per_share"], errors="coerce")
    counts, edges = np.histogram(fair_values.dropna(), bins=bins)
    return pd.DataFrame(
        {
            "bin_start": edges[:-1],
            "bin_end": edges[1:],
            "bin_midpoint": (edges[:-1] + edges[1:]) / 2,
            "count": counts,
        }
    )


def create_percentile_summary_data(summary: dict[str, Any]) -> pd.DataFrame:
    """Return percentile output in a chart-friendly long format."""
    percentile_map = {
        "5th": "percentile_5",
        "10th": "percentile_10",
        "25th": "percentile_25",
        "Median": "median_fair_value",
        "75th": "percentile_75",
        "90th": "percentile_90",
        "95th": "percentile_95",
    }
    return pd.DataFrame(
        [
            {"percentile": label, "fair_value_per_share": summary[key]}
            for label, key in percentile_map.items()
        ]
    )


def create_tornado_data(sensitivity: pd.DataFrame) -> pd.DataFrame:
    """Return sorted correlation data for a tornado-style sensitivity chart."""
    if sensitivity.empty:
        return sensitivity.copy()
    sort_column = "absolute_correlation" if "absolute_correlation" in sensitivity.columns else "valuation_impact_score"
    return sensitivity.sort_values(sort_column, ascending=True).reset_index(drop=True)


def _default_base_assumptions(inputs: MonteCarloDCFInputs) -> DCFAssumptions:
    """Create a DCF assumptions object from Monte Carlo base inputs."""
    return DCFAssumptions(
        forecast_years=inputs.forecast_years,
        revenue_growth=inputs.base_revenue_growth,
        ebit_margin=inputs.base_ebit_margin,
        tax_rate=inputs.base_tax_rate,
        wacc=inputs.base_wacc,
        terminal_growth=inputs.base_terminal_growth,
    )


def run_monte_carlo_dcf(inputs: MonteCarloDCFInputs) -> MonteCarloDCFResult:
    """Run the structured Monte Carlo workflow and return exportable outputs."""
    validate_monte_carlo_inputs(inputs)
    rng = np.random.default_rng(inputs.random_seed)
    rows: list[dict[str, Any]] = []
    use_fcf_margin = "fcf_margin" in inputs.distributions or inputs.base_fcf_margin is not None

    for simulation_id in range(1, inputs.simulations + 1):
        assumptions = {
            "revenue_growth": _draw_assumption(
                inputs, "revenue_growth", inputs.base_revenue_growth, rng
            ),
            "ebit_margin": _draw_assumption(
                inputs, "ebit_margin", inputs.base_ebit_margin, rng
            ),
            "tax_rate": _draw_assumption(inputs, "tax_rate", inputs.base_tax_rate, rng),
            "wacc": _draw_assumption(inputs, "wacc", inputs.base_wacc, rng),
            "terminal_growth": _draw_assumption(
                inputs, "terminal_growth", inputs.base_terminal_growth, rng
            ),
        }
        if use_fcf_margin:
            assumptions["fcf_margin"] = _draw_assumption(
                inputs, "fcf_margin", inputs.base_fcf_margin, rng
            )
        else:
            assumptions["fcf_conversion"] = _draw_assumption(
                inputs, "fcf_conversion", inputs.base_fcf_conversion, rng
            )
        rows.append(
            {
                "simulation_id": simulation_id,
                **run_single_dcf_simulation(inputs, assumptions),
            }
        )

    simulation_df = pd.DataFrame(rows)
    historical_financials = inputs.historical_financials
    base_assumptions = inputs.base_assumptions or _default_base_assumptions(inputs)
    historical_warning = None
    if historical_financials is not None and not historical_financials.empty:
        driver_ranking = identify_value_drivers(historical_financials, base_assumptions)
    else:
        historical_warning = (
            "Historical financials were not available, so default distribution assumptions were used."
        )
        driver_ranking = pd.DataFrame(
            [
                {
                    "value_driver": driver,
                    "base_value": getattr(inputs, f"base_{driver}", np.nan),
                    "historical_average": np.nan,
                    "historical_volatility": np.nan,
                    "valuation_impact_score": np.nan,
                    "uncertainty_score": np.nan,
                    "final_priority_score": np.nan,
                    "explanation": DRIVER_EXPLANATIONS.get(driver, "Simulation assumption."),
                }
                for driver in list(inputs.distributions.keys()) + ["net_debt", "diluted_shares"]
            ]
        )
    distribution_table = explain_distribution_choices(inputs.distributions, driver_ranking)
    value_driver_table = create_value_driver_table(driver_ranking, distribution_table)
    summary = summarize_monte_carlo_results(simulation_df, inputs, value_driver_table)
    if historical_warning:
        summary["historical_financials_warning"] = historical_warning
    explanation = generate_monte_carlo_explanation(summary, value_driver_table, distribution_table)
    sensitivity = calculate_assumption_sensitivity(simulation_df)
    return MonteCarloDCFResult(
        simulation_df=simulation_df,
        summary=summary,
        sensitivity=sensitivity,
        value_driver_table=value_driver_table,
        explanation=explanation,
    )


def build_inputs_from_financials(
    financials: pd.DataFrame,
    *,
    ticker: str,
    company_name: str,
    current_price: float,
    base_case_fair_value: float | None = None,
    forecast_years: int = 5,
    simulations: int = 10_000,
    random_seed: int | None = 42,
    distributions: dict[str, DistributionSpec] | None = None,
    historical_financials: pd.DataFrame | None = None,
    base_assumptions: DCFAssumptions | None = None,
) -> MonteCarloDCFInputs:
    """Create simulation inputs from the latest row of a clean financial table."""
    latest = financials.sort_values("year").iloc[-1]
    latest_revenue = float(latest["revenue"])
    free_cash_flow = float(latest["free_cash_flow"])
    net_income = float(latest["net_income"])
    base_fcf_margin = free_cash_flow / latest_revenue if latest_revenue else None
    base_fcf_conversion = free_cash_flow / net_income if net_income else None
    return MonteCarloDCFInputs(
        ticker=ticker,
        company_name=company_name,
        latest_revenue=latest_revenue,
        current_price=float(current_price),
        cash=float(latest["cash"]),
        debt=float(latest["total_debt"]),
        diluted_shares=float(latest["diluted_shares"]),
        forecast_years=forecast_years,
        simulations=simulations,
        random_seed=random_seed,
        base_revenue_growth=0.06,
        base_ebit_margin=float(latest["ebit"]) / latest_revenue,
        base_tax_rate=0.22,
        base_fcf_margin=base_fcf_margin,
        base_fcf_conversion=base_fcf_conversion,
        base_wacc=0.09,
        base_terminal_growth=0.025,
        base_case_fair_value=base_case_fair_value,
        distributions=distributions or NASDAQ_DEFAULT_DISTRIBUTIONS.copy(),
        historical_financials=historical_financials,
        base_assumptions=base_assumptions,
    )


if __name__ == "__main__":
    demo_inputs = MonteCarloDCFInputs(
        ticker="NDAQ",
        company_name="Nasdaq, Inc.",
        latest_revenue=8_262,
        current_price=90,
        cash=604,
        debt=8_573,
        diluted_shares=578.6,
        simulations=1_000,
        random_seed=42,
    )
    demo_result = run_monte_carlo_dcf(demo_inputs)
    print(demo_result.simulation_df.head())
    print(demo_result.summary)
    print(demo_result.value_driver_table)
    print(demo_result.explanation)
