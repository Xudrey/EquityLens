"""Minimal SEC Company Facts loader with sample-data fallback support."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .config import COMPANY

SEC_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001120193.json"
CACHE_PATH = Path("data/cache/ndaq_companyfacts.json")


@dataclass
class FinancialDataResult:
    financials: pd.DataFrame
    source_data: pd.DataFrame
    tags_used: pd.DataFrame
    quality_notes: pd.DataFrame
    metadata: dict[str, Any]


class SECDataError(RuntimeError):
    """Raised when SEC data cannot be loaded."""


def _annual_usd_facts(payload: dict[str, Any], tag: str) -> pd.DataFrame:
    facts = payload.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {})
    unit_rows = facts.get("USD") or facts.get("shares") or facts.get("USD/shares") or []
    rows = []
    for item in unit_rows:
        form = item.get("form")
        fp = item.get("fp")
        fy = item.get("fy")
        if form not in {"10-K", "10-K/A"} or fp != "FY" or fy is None:
            continue
        val = item.get("val")
        if val is None:
            continue
        rows.append({"year": int(fy), "tag": tag, "value": float(val), "form": form, "filed": item.get("filed")})
    return pd.DataFrame(rows)


def _pick_latest(payload: dict[str, Any], metric: str, tags: list[str], scale: float = 1_000_000) -> tuple[pd.Series | None, pd.DataFrame]:
    all_rows = []
    for tag in tags:
        rows = _annual_usd_facts(payload, tag)
        if not rows.empty:
            rows["metric"] = metric
            all_rows.append(rows)
    if not all_rows:
        return None, pd.DataFrame()
    combined = pd.concat(all_rows, ignore_index=True).sort_values(["year", "filed"])
    chosen = combined.drop_duplicates("year", keep="last").copy()
    chosen["value"] = chosen["value"] / scale
    return chosen.set_index("year")["value"], combined


def fetch_companyfacts(cache_path: Path = CACHE_PATH) -> tuple[dict[str, Any], bool]:
    """Fetch SEC Company Facts or use a cached response."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    user_agent = os.getenv("SEC_USER_AGENT", "EquityLens academic portfolio project contact@example.com")
    try:
        response = requests.get(SEC_URL, headers={"User-Agent": user_agent}, timeout=20)
        if response.status_code != 200:
            raise SECDataError(f"SEC request failed with HTTP {response.status_code}: {response.text[:300]}")
        payload = response.json()
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload, False
    except Exception as exc:
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8")), True
        raise SECDataError(f"Unable to retrieve SEC Company Facts and no cached response is available. {exc}") from exc


def load_sec_financial_data(current_share_price: float, years: int = 7, cache_path: Path = CACHE_PATH) -> FinancialDataResult:
    """Load recent annual NDAQ financials from SEC Company Facts."""
    payload, from_cache = fetch_companyfacts(cache_path)
    tag_map = {
        "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
        "ebit": ["OperatingIncomeLoss"],
        "net_income": ["NetIncomeLoss"],
        "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
        "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
        "cash": ["CashAndCashEquivalentsAtCarryingValue"],
        "total_debt": ["LongTermDebt", "LongTermDebtAndFinanceLeaseObligations"],
        "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    }
    series_by_metric = {}
    source_rows = []
    tags_used = []
    notes = []
    for metric, tags in tag_map.items():
        series, raw = _pick_latest(payload, metric, tags, scale=1 if metric == "diluted_shares" else 1_000_000)
        if series is None:
            notes.append({"severity": "Warning", "metric": metric, "note": "No SEC tag found; field will be blank."})
            continue
        series_by_metric[metric] = series
        source_rows.append(raw.assign(metric=metric))
        tags_used.append({"metric": metric, "tag": raw["tag"].iloc[0], "method": "annual FY 10-K fact"})
    financials = pd.DataFrame(series_by_metric).sort_index().tail(years).reset_index().rename(columns={"index": "year"})
    financials["free_cash_flow"] = financials["operating_cash_flow"] - financials["capex"].abs()
    financials["current_share_price"] = float(current_share_price)
    required = ["year", "revenue", "ebit", "net_income", "operating_cash_flow", "capex", "free_cash_flow", "cash", "total_debt", "diluted_shares", "current_share_price"]
    for column in required:
        if column not in financials.columns:
            financials[column] = pd.NA
    metadata = {
        "source": "SEC EDGAR Company Facts API" + (" (cached)" if from_cache else ""),
        "company": COMPANY.company_name,
        "ticker": COMPANY.ticker,
        "cik": COMPANY.cik,
        "api_url": SEC_URL,
        "fiscal_years": f"{int(financials['year'].min())}-{int(financials['year'].max())}" if not financials.empty else "Not available",
        "is_sample_fallback": False,
    }
    return FinancialDataResult(
        financials=financials[required],
        source_data=pd.concat(source_rows, ignore_index=True) if source_rows else pd.DataFrame(),
        tags_used=pd.DataFrame(tags_used),
        quality_notes=pd.DataFrame(notes),
        metadata=metadata,
    )
