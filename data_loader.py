"""Load local sample financial data."""

from pathlib import Path
import pandas as pd

REQUIRED_COLUMNS = [
    "year",
    "revenue",
    "ebit",
    "net_income",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "cash",
    "total_debt",
    "diluted_shares",
    "current_share_price",
]


def load_financial_data(path: str | Path) -> pd.DataFrame:
    """Load and validate a financial CSV."""
    data = pd.read_csv(path)
    missing = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing:
        raise ValueError(f"Financial data is missing required columns: {', '.join(missing)}")
    for column in REQUIRED_COLUMNS:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.sort_values("year").reset_index(drop=True)
