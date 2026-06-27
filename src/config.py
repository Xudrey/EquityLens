"""Project configuration and base-case assumptions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CompanyConfig:
    ticker: str = "NDAQ"
    company_name: str = "Nasdaq, Inc."
    currency_units: str = "USD millions, except per-share data"


@dataclass(frozen=True)
class DCFAssumptions:
    forecast_years: int = 5
    revenue_growth: float = 0.065
    ebit_margin: float = 0.275
    tax_rate: float = 0.24
    da_pct_revenue: float = 0.065
    capex_pct_revenue: float = 0.038
    nwc_pct_revenue: float = 0.01
    wacc: float = 0.085
    terminal_growth: float = 0.025


COMPANY = CompanyConfig()
BASE_CASE = DCFAssumptions()

