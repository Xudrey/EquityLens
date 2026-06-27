import gzip
import inspect
import json
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from src.sec_data import (
    build_sec_financials,
    fetch_companyfacts,
    load_sec_financial_data,
    test_sec_connection,
)


def _duration_fact(year: int, value: float, accession: str, form: str = "10-K"):
    return {
        "start": f"{year}-01-01",
        "end": f"{year}-12-31",
        "val": value,
        "accn": accession,
        "fy": year,
        "fp": "FY",
        "form": form,
        "filed": f"{year + 1}-02-20",
        "frame": f"CY{year}",
    }


def _instant_fact(year: int, value: float, accession: str):
    return {
        "end": f"{year}-12-31",
        "val": value,
        "accn": accession,
        "fy": year,
        "fp": "FY",
        "form": "10-K",
        "filed": f"{year + 1}-02-20",
        "frame": f"CY{year}I",
    }


def _fixture_payload():
    years = range(2019, 2025)
    facts = {"us-gaap": {}, "dei": {}}

    def add_duration(tag, unit, base):
        values = [_duration_fact(year, base + (year - 2019) * base * 0.05, f"acc-{year}") for year in years]
        values.append(_duration_fact(2024, base * 99, "quarter-noise", form="10-Q"))
        facts["us-gaap"][tag] = {"units": {unit: values}}

    def add_instant(tag, unit, base):
        facts["us-gaap"][tag] = {
            "units": {unit: [_instant_fact(year, base + (year - 2019) * 10, f"acc-{year}") for year in years]}
        }

    add_duration("RevenueFromContractWithCustomerExcludingAssessedTax", "USD", 5_000_000_000)
    add_duration("OperatingIncomeLoss", "USD", 1_000_000_000)
    add_duration("NetIncomeLoss", "USD", 700_000_000)
    add_duration("NetCashProvidedByUsedInOperatingActivities", "USD", 900_000_000)
    add_duration("PaymentsToAcquirePropertyPlantAndEquipment", "USD", 150_000_000)
    add_duration("WeightedAverageNumberOfDilutedSharesOutstanding", "shares", 575_000_000)
    add_duration("EarningsPerShareDiluted", "USD/shares", 2.00)
    add_instant("CashAndCashEquivalentsAtCarryingValue", "USD", 400_000_000)
    add_instant("LongTermDebtCurrent", "USD", 100_000_000)
    add_instant("LongTermDebtNoncurrent", "USD", 900_000_000)
    return {"cik": 1120193, "entityName": "Nasdaq, Inc.", "facts": facts}


def test_sec_facts_are_annual_and_model_ready():
    result = build_sec_financials(_fixture_payload(), current_share_price=75.0, years=5)
    assert result.financials["year"].tolist() == [2020, 2021, 2022, 2023, 2024]
    latest = result.financials.iloc[-1]
    assert latest["revenue"] < 10_000
    assert latest["free_cash_flow"] == latest["operating_cash_flow"] - latest["capex"]
    assert latest["total_debt"] == 1_000.0001
    assert latest["current_share_price"] == 75.0
    assert "OperatingIncomeLoss" in latest["source"]
    assert not result.source_data.empty
    assert not result.tags_used.empty


def test_quarterly_facts_are_ignored():
    result = build_sec_financials(_fixture_payload(), current_share_price=75.0, years=5)
    assert result.financials.iloc[-1]["revenue"] < 10_000


def test_gzip_companyfacts_response_is_supported():
    payload = _fixture_payload()

    class FakeResponse:
        headers = {"Content-Encoding": "gzip"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return gzip.compress(json.dumps(payload).encode("utf-8"))

    with TemporaryDirectory() as temp_dir:
        with patch("src.sec_data.requests", None), patch(
            "src.sec_data.urlopen", return_value=FakeResponse()
        ):
            result, from_cache = fetch_companyfacts(
                cache_path=f"{temp_dir}/companyfacts.json", cache_hours=0
            )
    assert result["cik"] == 1120193
    assert from_cache is False


def test_sec_loader_accepts_price_metadata():
    parameters = inspect.signature(load_sec_financial_data).parameters
    assert "current_share_price" in parameters
    assert "price_source" in parameters
    assert "price_timestamp" in parameters


def test_sec_http_failure_returns_diagnostics():
    response = SimpleNamespace(status_code=403, text="Forbidden by test", json=lambda: {})
    fake_requests = SimpleNamespace(get=lambda *args, **kwargs: response)
    diagnostics = {}
    with TemporaryDirectory() as temp_dir, patch("src.sec_data.requests", fake_requests):
        try:
            fetch_companyfacts(
                cache_path=f"{temp_dir}/missing.json",
                diagnostics=diagnostics,
                allow_stale_cache_on_error=False,
            )
        except Exception as exc:
            assert "SEC URL:" in str(exc)
        else:
            raise AssertionError("Expected SEC failure")
    assert diagnostics["http_status_code"] == 403
    assert diagnostics["response_text_preview"] == "Forbidden by test"


def test_connection_result_has_stable_schema():
    response = SimpleNamespace(status_code=503, text="Service unavailable", json=lambda: {})
    fake_requests = SimpleNamespace(get=lambda *args, **kwargs: response)
    with TemporaryDirectory() as temp_dir, patch("src.sec_data.requests", fake_requests):
        result = test_sec_connection(cache_path=f"{temp_dir}/companyfacts.json")
    assert result["ok"] is False
    assert result["message"]
    assert result["status_code"] == 503
    assert "Service unavailable" in result["error"]
