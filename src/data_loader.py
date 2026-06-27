"""Load and validate historical financial data."""

from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = {
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
}


def load_financial_data(csv_path: str | Path) -> pd.DataFrame:
    """Load a CSV, validate its schema, and return ascending annual data."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Financial data file not found: {path}")

    data = pd.read_csv(path)
    missing = sorted(REQUIRED_COLUMNS - set(data.columns))
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    if data.empty:
        raise ValueError("Financial data file contains no rows.")

    data = data.copy()
    for column in REQUIRED_COLUMNS:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    if data[list(REQUIRED_COLUMNS)].isna().any().any():
        bad = data[list(REQUIRED_COLUMNS)].columns[
            data[list(REQUIRED_COLUMNS)].isna().any()
        ].tolist()
        raise ValueError(f"Non-numeric or missing values found in: {', '.join(bad)}")
    if data["year"].duplicated().any():
        raise ValueError("Each year must appear only once.")

    data["year"] = data["year"].astype(int)
    # Treat capex as a positive cash outflow throughout the model.
    data["capex"] = data["capex"].abs()
    data["free_cash_flow"] = data["free_cash_flow"].fillna(
        data["operating_cash_flow"] - data["capex"]
    )
    return data.sort_values("year").reset_index(drop=True)

