import numpy as np
import pandas as pd
import pytest

from src.monte_carlo_dcf import (
    DistributionSpec,
    MonteCarloDCFInputs,
    apply_simulation_constraints,
    build_inputs_from_financials,
    explain_distribution_choices,
    identify_value_drivers,
    run_monte_carlo_dcf,
    sample_distribution,
)
from src.config import BASE_CASE


def example_inputs(simulations: int = 500) -> MonteCarloDCFInputs:
    return MonteCarloDCFInputs(
        ticker="NDAQ",
        company_name="Nasdaq, Inc.",
        latest_revenue=8_262,
        current_price=90,
        cash=604,
        debt=8_573,
        diluted_shares=578.6,
        simulations=simulations,
        random_seed=42,
    )


def test_sample_distribution_supports_triangular():
    rng = np.random.default_rng(42)
    values = sample_distribution(
        DistributionSpec("triangular", low=0.03, mode=0.06, high=0.09),
        rng,
        size=100,
    )
    assert len(values) == 100
    assert values.min() >= 0.03
    assert values.max() <= 0.09


def test_monte_carlo_returns_required_outputs():
    result = run_monte_carlo_dcf(example_inputs())
    simulation_df = result.simulation_df
    summary = result.summary
    required_columns = {
        "simulation_id",
        "revenue_growth",
        "ebit_margin",
        "tax_rate",
        "fcf_margin",
        "wacc",
        "terminal_growth",
        "terminal_value",
        "enterprise_value",
        "equity_value",
        "fair_value_per_share",
        "implied_upside_downside",
        "invalid_simulation_flag",
        "constraint_notes",
    }
    assert required_columns.issubset(simulation_df.columns)
    assert summary["simulations_run"] == 500
    assert summary["median_fair_value"] >= 0
    assert 0 <= summary["probability_above_current_price"] <= 1
    assert 0 <= summary["probability_below_current_price"] <= 1
    assert not result.value_driver_table.empty
    assert not result.sensitivity.empty
    assert "historical_financials_warning" in summary
    assert "The Monte Carlo simulation tests" in result.explanation


def test_monte_carlo_supports_legacy_tuple_unpacking():
    simulation_df, summary, sensitivity = run_monte_carlo_dcf(example_inputs(50))
    assert len(simulation_df) == 50
    assert summary["simulations_run"] == 50
    assert not sensitivity.empty


def test_monte_carlo_is_reproducible_with_fixed_seed():
    first_result = run_monte_carlo_dcf(example_inputs())
    second_result = run_monte_carlo_dcf(example_inputs())
    pd.testing.assert_frame_equal(first_result.simulation_df, second_result.simulation_df)
    assert first_result.summary == second_result.summary


def test_wacc_guardrail_keeps_terminal_spread_positive():
    custom_inputs = MonteCarloDCFInputs(
        ticker="NDAQ",
        company_name="Nasdaq, Inc.",
        latest_revenue=8_262,
        current_price=90,
        cash=604,
        debt=8_573,
        diluted_shares=578.6,
        simulations=25,
        distributions={
            "revenue_growth": DistributionSpec("uniform", low=0.02, high=0.03),
            "ebit_margin": DistributionSpec("uniform", low=0.25, high=0.30),
            "tax_rate": DistributionSpec("uniform", low=0.20, high=0.24),
            "fcf_margin": DistributionSpec("uniform", low=0.20, high=0.24),
            "wacc": DistributionSpec("uniform", low=0.02, high=0.025),
            "terminal_growth": DistributionSpec("uniform", low=0.03, high=0.035),
        },
    )
    simulation_df = run_monte_carlo_dcf(custom_inputs).simulation_df
    assert (simulation_df["wacc"] >= simulation_df["terminal_growth"] + 0.01).all()


def test_constraints_return_notes_for_unrealistic_draws():
    constrained, notes = apply_simulation_constraints(
        {
            "revenue_growth": 0.12,
            "ebit_margin": 0.20,
            "tax_rate": 0.50,
            "fcf_margin": 0.40,
            "wacc": 0.02,
            "terminal_growth": 0.05,
        },
        example_inputs(),
    )
    assert constrained["tax_rate"] <= 0.35
    assert constrained["fcf_margin"] <= constrained["ebit_margin"]
    assert constrained["wacc"] >= constrained["terminal_growth"] + 0.01
    assert notes != "None"


def test_build_inputs_from_financials_uses_latest_row():
    financials = pd.DataFrame(
        [
            {
                "year": 2024,
                "revenue": 7_400,
                "ebit": 1_798,
                "net_income": 1_117,
                "free_cash_flow": 1_732,
                "cash": 592,
                "total_debt": 8_582,
                "diluted_shares": 579.2,
            },
            {
                "year": 2025,
                "revenue": 8_262,
                "ebit": 2_331,
                "net_income": 1_788,
                "free_cash_flow": 1_989,
                "cash": 604,
                "total_debt": 8_573,
                "diluted_shares": 578.6,
            },
        ]
    )
    inputs = build_inputs_from_financials(
        financials,
        ticker="NDAQ",
        company_name="Nasdaq, Inc.",
        current_price=90,
        simulations=100,
    )
    assert inputs.latest_revenue == pytest.approx(8_262)
    assert inputs.base_ebit_margin == pytest.approx(2_331 / 8_262)
    assert inputs.base_fcf_margin == pytest.approx(1_989 / 8_262)


def test_identify_value_drivers_and_distribution_explanations():
    financials = pd.DataFrame(
        [
            {
                "year": 2023,
                "revenue": 6_064,
                "ebit": 1_578,
                "net_income": 1_059,
                "free_cash_flow": 1_538,
                "cash": 453,
                "total_debt": 9_666,
                "diluted_shares": 508.4,
                "current_share_price": 90,
            },
            {
                "year": 2024,
                "revenue": 7_400,
                "ebit": 1_798,
                "net_income": 1_117,
                "free_cash_flow": 1_732,
                "cash": 592,
                "total_debt": 8_582,
                "diluted_shares": 579.2,
                "current_share_price": 90,
            },
            {
                "year": 2025,
                "revenue": 8_262,
                "ebit": 2_331,
                "net_income": 1_788,
                "free_cash_flow": 1_989,
                "cash": 604,
                "total_debt": 8_573,
                "diluted_shares": 578.6,
                "current_share_price": 90,
            },
        ]
    )
    drivers = identify_value_drivers(financials, BASE_CASE)
    explanations = explain_distribution_choices(example_inputs().distributions, drivers)
    assert {
        "value_driver",
        "base_value",
        "valuation_impact_score",
        "uncertainty_score",
        "final_priority_score",
        "explanation",
    }.issubset(drivers.columns)
    assert {"value_driver", "distribution", "parameters", "why_this_distribution"}.issubset(
        explanations.columns
    )
    assert "revenue_growth" in drivers["value_driver"].tolist()


def test_run_monte_carlo_uses_historical_financials_from_inputs():
    financials = pd.DataFrame(
        [
            {
                "year": 2023,
                "revenue": 6_064.0,
                "ebit": 1_578.0,
                "net_income": 1_059.0,
                "free_cash_flow": 1_538.0,
                "cash": 453.0,
                "total_debt": 9_666.0,
                "diluted_shares": 508.4,
                "current_share_price": 90.0,
            },
            {
                "year": 2024,
                "revenue": 7_400.0,
                "ebit": 1_798.0,
                "net_income": 1_117.0,
                "free_cash_flow": 1_732.0,
                "cash": 592.0,
                "total_debt": 8_582.0,
                "diluted_shares": 579.2,
                "current_share_price": 90.0,
            },
            {
                "year": 2025,
                "revenue": 8_262.0,
                "ebit": 2_331.0,
                "net_income": 1_788.0,
                "free_cash_flow": 1_989.0,
                "cash": 604.0,
                "total_debt": 8_573.0,
                "diluted_shares": 578.6,
                "current_share_price": 90.0,
            },
        ]
    )
    inputs = build_inputs_from_financials(
        financials,
        ticker="NDAQ",
        company_name="Nasdaq, Inc.",
        current_price=90.0,
        simulations=50,
        historical_financials=financials,
        base_assumptions=BASE_CASE,
    )
    result = run_monte_carlo_dcf(inputs)
    assert "historical_financials_warning" not in result.summary
    assert result.value_driver_table["historical_average"].notna().any()
