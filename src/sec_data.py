"""SEC EDGAR Company Facts ingestion for Nasdaq, Inc. (NDAQ)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import gzip
import json
import os
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zlib

import pandas as pd

try:
    import requests
except ImportError:  # The app can still explain how to install dependencies.
    requests = None


NDAQ_CIK = "0001120193"
NDAQ_TICKER = "NDAQ"
NDAQ_COMPANY = "Nasdaq, Inc."
COMPANYFACTS_URL = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{NDAQ_CIK}.json"
DEFAULT_USER_AGENT = "EquityLens academic portfolio project contact@example.com"
MODEL_COLUMNS = [
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


class SECDataError(RuntimeError):
    """Raised when SEC data cannot support a reliable model run."""

    def __init__(self, message: str, diagnostics: dict[str, Any] | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


@dataclass
class SECDataResult:
    """Clean model inputs plus the audit trail behind them."""

    financials: pd.DataFrame
    source_data: pd.DataFrame
    tags_used: pd.DataFrame
    quality_notes: pd.DataFrame
    metadata: dict[str, Any]


TAG_CANDIDATES: dict[str, list[tuple[str, str, str, bool, str]]] = {
    "revenue": [
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD", False, "reported"),
        ("us-gaap", "Revenues", "USD", False, "fallback"),
        ("us-gaap", "SalesRevenueNet", "USD", False, "fallback"),
    ],
    "ebit": [
        ("us-gaap", "OperatingIncomeLoss", "USD", False, "reported"),
        (
            "us-gaap",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "USD",
            False,
            "pre-tax income proxy",
        ),
    ],
    "net_income": [
        ("us-gaap", "NetIncomeLoss", "USD", False, "reported"),
        ("us-gaap", "ProfitLoss", "USD", False, "fallback"),
    ],
    "operating_cash_flow": [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities", "USD", False, "reported"),
    ],
    "capex": [
        ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment", "USD", False, "reported"),
        ("us-gaap", "PaymentsToAcquireProductiveAssets", "USD", False, "fallback"),
    ],
    "cash": [
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue", "USD", True, "reported"),
        (
            "us-gaap",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "USD",
            True,
            "includes restricted cash",
        ),
    ],
    "diluted_shares": [
        ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", "shares", False, "reported"),
        ("dei", "EntityCommonStockSharesOutstanding", "shares", True, "period-end shares proxy"),
    ],
    "diluted_eps": [
        ("us-gaap", "EarningsPerShareDiluted", "USD/shares", False, "reported"),
    ],
}

DEBT_AGGREGATE_TAGS = [
    ("us-gaap", "LongTermDebtAndFinanceLeaseObligations", "USD", True, "reported aggregate"),
    ("us-gaap", "LongTermDebt", "USD", True, "reported aggregate"),
]
DEBT_CURRENT_TAGS = [
    ("us-gaap", "LongTermDebtAndFinanceLeaseObligationsCurrent", "USD", True, "current component"),
    ("us-gaap", "LongTermDebtCurrent", "USD", True, "current component"),
    ("us-gaap", "ShortTermBorrowings", "USD", True, "short-term debt fallback"),
]
DEBT_NONCURRENT_TAGS = [
    ("us-gaap", "LongTermDebtAndFinanceLeaseObligationsNoncurrent", "USD", True, "noncurrent component"),
    ("us-gaap", "LongTermDebtNoncurrent", "USD", True, "noncurrent component"),
]


def fetch_companyfacts(
    *,
    user_agent: str | None = None,
    cache_path: str | Path | None = None,
    cache_hours: int = 6,
    timeout: int = 30,
    force_refresh: bool = False,
    allow_stale_cache_on_error: bool = True,
    diagnostics: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Fetch NDAQ Company Facts, using a recent SEC cache when available."""
    diagnostic = diagnostics if diagnostics is not None else {}
    configured_user_agent = user_agent or os.getenv("SEC_USER_AGENT")
    diagnostic.update(
        {
            "sec_url": COMPANYFACTS_URL,
            "sec_user_agent_found": bool(configured_user_agent),
            "http_status_code": None,
            "response_text_preview": None,
            "from_cache": False,
            "cache_path": str(cache_path or "data/cache/ndaq_companyfacts.json"),
        }
    )
    cache = Path(cache_path) if cache_path else Path("data/cache/ndaq_companyfacts.json")
    if cache.exists() and not force_refresh:
        age_seconds = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
        if age_seconds <= cache_hours * 3600:
            diagnostic["from_cache"] = True
            return json.loads(cache.read_text()), True

    headers = {
        "User-Agent": configured_user_agent or DEFAULT_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    }
    try:
        if requests is not None:
            response = requests.get(COMPANYFACTS_URL, headers=headers, timeout=timeout)
            diagnostic["http_status_code"] = response.status_code
            if response.status_code != 200:
                diagnostic["response_text_preview"] = response.text[:500]
                raise SECDataError("SEC returned a non-success HTTP status.", diagnostic)
            payload = response.json()
        else:
            request = Request(COMPANYFACTS_URL, headers=headers)
            with urlopen(request, timeout=timeout) as response:
                diagnostic["http_status_code"] = getattr(response, "status", 200)
                body = response.read()
                content_encoding = response.headers.get("Content-Encoding", "").lower()
                if content_encoding == "gzip":
                    body = gzip.decompress(body)
                elif content_encoding == "deflate":
                    body = zlib.decompress(body)
                payload = json.loads(body.decode("utf-8"))
    except Exception as exc:
        if isinstance(exc, HTTPError):
            diagnostic["http_status_code"] = exc.code
            try:
                diagnostic["response_text_preview"] = exc.read(500).decode("utf-8", errors="replace")
            except Exception:
                pass
        diagnostic["error_type"] = type(exc).__name__
        diagnostic["error_message"] = str(exc)
        if cache.exists() and allow_stale_cache_on_error:
            diagnostic["from_cache"] = True
            return json.loads(cache.read_text()), True
        details = (
            "Unable to retrieve SEC Company Facts and no cached SEC response is available.\n"
            f"SEC URL: {diagnostic['sec_url']}\n"
            f"SEC_USER_AGENT found: {diagnostic['sec_user_agent_found']}\n"
            f"HTTP status code: {diagnostic['http_status_code']}\n"
            f"Response preview: {diagnostic['response_text_preview'] or 'Not available'}\n"
            f"Underlying error: {diagnostic['error_message']}"
        )
        raise SECDataError(details, diagnostic) from exc

    if payload.get("cik") not in {int(NDAQ_CIK), NDAQ_CIK}:
        raise SECDataError("The SEC response did not match Nasdaq's expected CIK.", diagnostic)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload))
    return payload, False


def test_sec_connection(
    *,
    user_agent: str | None = None,
    timeout: int = 15,
    cache_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run a live SEC connectivity test without silently using cached data."""
    diagnostic: dict[str, Any] = {}
    try:
        fetch_companyfacts(
            user_agent=user_agent,
            cache_path=cache_path,
            timeout=timeout,
            force_refresh=True,
            allow_stale_cache_on_error=False,
            diagnostics=diagnostic,
        )
        diagnostic.update(
            {
                "ok": True,
                "message": "SEC EDGAR Company Facts is reachable for NDAQ / CIK0001120193.",
                "status_code": diagnostic.get("http_status_code"),
                "error": None,
                # Backward-compatible aliases for older app code.
                "success": True,
                "error_message": None,
            }
        )
    except SECDataError as exc:
        diagnostic.update(exc.diagnostics)
        diagnostic.update(
            {
                "ok": False,
                "message": "SEC EDGAR Company Facts connection failed.",
                "status_code": diagnostic.get("http_status_code"),
                "error": str(exc),
                "success": False,
                "error_message": str(exc),
            }
        )
    return diagnostic


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _fact_score(fact: dict[str, Any], *, instant: bool, year: int) -> tuple[Any, ...]:
    end = _parse_date(fact.get("end"))
    start = _parse_date(fact.get("start"))
    expected_frame = f"CY{year}I" if instant else f"CY{year}"
    duration_score = 0
    if not instant and start and end:
        duration_score = -abs((end - start).days - 364)
    return (
        fact.get("fp") == "FY",
        fact.get("frame") == expected_frame,
        fact.get("form") == "10-K/A",
        duration_score,
        fact.get("filed", ""),
        fact.get("accn", ""),
    )


def _annual_facts(
    payload: dict[str, Any],
    taxonomy: str,
    tag: str,
    unit: str,
    *,
    instant: bool,
) -> dict[int, dict[str, Any]]:
    concept = payload.get("facts", {}).get(taxonomy, {}).get(tag, {})
    facts = concept.get("units", {}).get(unit, [])
    by_year: dict[int, list[dict[str, Any]]] = {}
    for fact in facts:
        if fact.get("form") not in {"10-K", "10-K/A"}:
            continue
        end = _parse_date(fact.get("end"))
        if not end or not isinstance(fact.get("val"), (int, float)):
            continue
        if not instant:
            start = _parse_date(fact.get("start"))
            if not start or not 300 <= (end - start).days <= 400:
                continue
        by_year.setdefault(end.year, []).append(fact)
    return {
        year: max(candidates, key=lambda fact: _fact_score(fact, instant=instant, year=year))
        for year, candidates in by_year.items()
    }


def _select_metric(
    payload: dict[str, Any],
    metric: str,
    candidates: Iterable[tuple[str, str, str, bool, str]],
) -> tuple[dict[int, float], list[dict[str, Any]], list[dict[str, Any]]]:
    values: dict[int, float] = {}
    sources: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for rank, (taxonomy, tag, unit, instant, method) in enumerate(candidates, start=1):
        for year, fact in _annual_facts(payload, taxonomy, tag, unit, instant=instant).items():
            if year in values:
                continue
            scale = 1_000_000 if unit in {"USD", "shares"} else 1
            values[year] = float(fact["val"]) / scale
            sources.append(
                {
                    "year": year,
                    "metric": metric,
                    "value": values[year],
                    "taxonomy": taxonomy,
                    "tag": tag,
                    "unit": f"{unit} millions" if scale == 1_000_000 else unit,
                    "method": method,
                    "fallback_rank": rank,
                    "form": fact.get("form"),
                    "filed": fact.get("filed"),
                    "period_start": fact.get("start"),
                    "period_end": fact.get("end"),
                    "accession": fact.get("accn"),
                    "source_url": COMPANYFACTS_URL,
                }
            )
            if rank > 1 or method != "reported":
                notes.append(
                    {
                        "severity": "Warning",
                        "metric": metric,
                        "year": year,
                        "note": f"Used {tag} ({method}) because the preferred SEC concept was unavailable.",
                    }
                )
    return values, sources, notes


def _select_debt(payload: dict[str, Any]) -> tuple[dict[int, float], list[dict[str, Any]], list[dict[str, Any]]]:
    aggregate, aggregate_sources, notes = _select_metric(payload, "total_debt", DEBT_AGGREGATE_TAGS)
    current, current_sources, current_notes = _select_metric(payload, "debt_current", DEBT_CURRENT_TAGS)
    noncurrent, noncurrent_sources, noncurrent_notes = _select_metric(
        payload, "debt_noncurrent", DEBT_NONCURRENT_TAGS
    )
    values = dict(aggregate)
    sources = list(aggregate_sources)
    notes.extend(current_notes + noncurrent_notes)
    component_sources = current_sources + noncurrent_sources
    for year in sorted(set(current) | set(noncurrent)):
        if year in values:
            continue
        if year in current and year in noncurrent:
            values[year] = current[year] + noncurrent[year]
            sources.extend(source for source in component_sources if source["year"] == year)
            notes.append(
                {
                    "severity": "Info",
                    "metric": "total_debt",
                    "year": year,
                    "note": "Calculated total debt as current debt plus noncurrent debt.",
                }
            )
        else:
            partial = current.get(year, 0.0) + noncurrent.get(year, 0.0)
            if partial:
                values[year] = partial
                sources.extend(source for source in component_sources if source["year"] == year)
                notes.append(
                    {
                        "severity": "Warning",
                        "metric": "total_debt",
                        "year": year,
                        "note": "Debt uses only the available current or noncurrent component and may be incomplete.",
                    }
                )
    return values, sources, notes


def build_sec_financials(
    payload: dict[str, Any],
    *,
    current_share_price: float,
    price_source: str = "manual input",
    price_timestamp: str | None = None,
    years: int = 7,
    from_cache: bool = False,
) -> SECDataResult:
    """Convert a Company Facts response into model-ready annual financials."""
    if current_share_price <= 0:
        raise SECDataError("A positive current share price is required for the DCF comparison.")
    if not 5 <= years <= 10:
        raise ValueError("SEC history must include between 5 and 10 fiscal years.")

    values_by_metric: dict[str, dict[int, float]] = {}
    sources: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for metric, candidates in TAG_CANDIDATES.items():
        values, metric_sources, metric_notes = _select_metric(payload, metric, candidates)
        values_by_metric[metric] = values
        sources.extend(metric_sources)
        notes.extend(metric_notes)

    debt, debt_sources, debt_notes = _select_debt(payload)
    values_by_metric["total_debt"] = debt
    sources.extend(debt_sources)
    notes.extend(debt_notes)

    available_years = sorted(values_by_metric.get("revenue", {}))[-years:]
    if not available_years:
        raise SECDataError("No annual 10-K revenue facts were found for NDAQ.")

    rows: list[dict[str, Any]] = []
    source_frame = pd.DataFrame(sources)
    if not source_frame.empty:
        source_frame = source_frame[source_frame["year"].isin(available_years)].copy()
    notes = [note for note in notes if note.get("year") in available_years]
    for year in available_years:
        row: dict[str, Any] = {"year": year}
        for metric in TAG_CANDIDATES:
            row[metric] = values_by_metric.get(metric, {}).get(year, float("nan"))
        row["total_debt"] = values_by_metric["total_debt"].get(year, float("nan"))
        row["capex"] = abs(row["capex"]) if pd.notna(row["capex"]) else row["capex"]
        if pd.notna(row["operating_cash_flow"]) and pd.notna(row["capex"]):
            row["free_cash_flow"] = row["operating_cash_flow"] - row["capex"]
            notes.append(
                {
                    "severity": "Info",
                    "metric": "free_cash_flow",
                    "year": year,
                    "note": "Calculated as operating cash flow minus the absolute value of capital expenditures.",
                }
            )
        else:
            row["free_cash_flow"] = float("nan")
        row["current_share_price"] = float(current_share_price)
        year_sources = source_frame[source_frame["year"] == year] if not source_frame.empty else source_frame
        row["source"] = "; ".join(
            f"{item.metric}={item.taxonomy}:{item.tag}" for item in year_sources.itertuples()
        )
        rows.append(row)

    financials = pd.DataFrame(rows).sort_values("year").reset_index(drop=True)
    for column in MODEL_COLUMNS:
        if column not in financials:
            financials[column] = float("nan")

    # XBRL JSON values should be numeric, but explicit coercion protects charts
    # and ratios from mixed/object dtypes introduced by unusual filings.
    for column in MODEL_COLUMNS:
        financials[column] = pd.to_numeric(financials[column], errors="coerce")
    financials["year"] = financials["year"].astype("Int64")

    missing_fcf = (
        financials["free_cash_flow"].isna()
        & financials["operating_cash_flow"].notna()
        & financials["capex"].notna()
    )
    financials.loc[missing_fcf, "free_cash_flow"] = (
        financials.loc[missing_fcf, "operating_cash_flow"]
        - financials.loc[missing_fcf, "capex"].abs()
    )
    for year in financials.loc[missing_fcf, "year"].tolist():
        notes.append(
            {
                "severity": "Info",
                "metric": "free_cash_flow",
                "year": int(year),
                "note": "Filled missing free cash flow as operating cash flow minus absolute capex.",
            }
        )

    latest = financials.iloc[-1]
    essential = [
        "revenue",
        "ebit",
        "net_income",
        "operating_cash_flow",
        "capex",
        "free_cash_flow",
        "cash",
        "total_debt",
        "diluted_shares",
    ]
    missing_latest = [column for column in essential if pd.isna(latest[column])]
    if missing_latest:
        raise SECDataError(
            "The latest SEC fiscal year is missing required DCF fields: " + ", ".join(missing_latest)
        )
    if latest["diluted_shares"] <= 0:
        raise SECDataError("The latest SEC diluted share count is not positive.")

    for column in MODEL_COLUMNS[1:-1]:
        for year in financials.loc[financials[column].isna(), "year"].tolist():
            notes.append(
                {
                    "severity": "Warning",
                    "metric": column,
                    "year": int(year),
                    "note": "No suitable annual SEC 10-K fact was found; the field remains missing.",
                }
            )
    notes.extend(
        [
            {
                "severity": "Info",
                "metric": "current_share_price",
                "year": int(latest["year"]),
                "note": f"Market price supplied by {price_source}; SEC Company Facts does not provide live prices."
                + (f" Price timestamp: {price_timestamp}." if price_timestamp else ""),
            },
            {
                "severity": "Info" if not from_cache else "Warning",
                "metric": "data_source",
                "year": "All",
                "note": "Loaded from a cached SEC response." if from_cache else "Loaded from the live SEC Company Facts API.",
            },
        ]
    )

    quality_notes = pd.DataFrame(notes).drop_duplicates().reset_index(drop=True)
    tags_used = (
        source_frame.groupby(["metric", "taxonomy", "tag", "unit", "method", "fallback_rank"], dropna=False)
        .agg(first_year=("year", "min"), last_year=("year", "max"), observations=("year", "count"))
        .reset_index()
        if not source_frame.empty
        else pd.DataFrame()
    )
    metadata = {
        "source": "SEC EDGAR companyfacts API",
        "company": payload.get("entityName", NDAQ_COMPANY),
        "ticker": NDAQ_TICKER,
        "cik": NDAQ_CIK,
        "api_url": COMPANYFACTS_URL,
        "fiscal_years": f"{available_years[0]}-{available_years[-1]}",
        "years_included": available_years,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "from_cache": from_cache,
        "price_source": price_source,
        "price_timestamp": price_timestamp,
    }
    ordered = MODEL_COLUMNS + ["diluted_eps", "source"]
    return SECDataResult(
        financials=financials[ordered],
        source_data=source_frame.sort_values(["year", "metric"]).reset_index(drop=True),
        tags_used=tags_used,
        quality_notes=quality_notes,
        metadata=metadata,
    )


def load_sec_financial_data(
    *,
    current_share_price: float,
    price_source: str = "manual input",
    price_timestamp: str | None = None,
    years: int = 7,
    user_agent: str | None = None,
    cache_path: str | Path | None = None,
) -> SECDataResult:
    """Fetch and normalize NDAQ SEC Company Facts for the EquityLens model."""
    payload, from_cache = fetch_companyfacts(user_agent=user_agent, cache_path=cache_path)
    return build_sec_financials(
        payload,
        current_share_price=current_share_price,
        price_source=price_source,
        price_timestamp=price_timestamp,
        years=years,
        from_cache=from_cache,
    )
