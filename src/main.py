"""Run the SEC-grounded EquityLens analysis and create the Excel report."""

import argparse
from pathlib import Path

from .config import BASE_CASE, COMPANY
from .dcf import run_dcf
from .excel_export import export_excel_report
from .financial_analysis import calculate_financial_metrics, summarize_financial_trends
from .market_data import get_current_price
from .memo import generate_investment_memo
from .sec_data import load_sec_financial_data
from .sensitivity import revenue_margin_sensitivity, wacc_terminal_growth_sensitivity


ROOT = Path(__file__).resolve().parents[1]


def build_report(current_share_price: float | None = None, years: int = 7) -> Path:
    if current_share_price is not None and current_share_price > 0:
        price_result = {
            "current_price": float(current_share_price),
            "price_source": "manual input",
            "price_timestamp": None,
        }
    else:
        price_result = get_current_price(COMPANY.ticker)
        if price_result["current_price"] is None:
            raise RuntimeError(
                f"Automatic NDAQ price fetch failed: {price_result['error_message']} "
                "Run again with --share-price PRICE to use the manual fallback."
            )
    sec_result = load_sec_financial_data(
        current_share_price=price_result["current_price"],
        price_source=price_result["price_source"],
        price_timestamp=price_result["price_timestamp"],
        years=years,
        cache_path=ROOT / "data" / "cache" / "ndaq_companyfacts.json",
    )
    data = sec_result.financials
    ratios = calculate_financial_metrics(data)
    trends = summarize_financial_trends(ratios)
    dcf_results = run_dcf(data, BASE_CASE)
    sensitivities = {
        "wacc_terminal_growth": wacc_terminal_growth_sensitivity(data, BASE_CASE),
        "revenue_growth_ebit_margin": revenue_margin_sensitivity(data, BASE_CASE),
    }
    memo = generate_investment_memo(
        trends,
        dcf_results,
        sensitivities,
        data_source=sec_result.metadata["source"],
        price_source=sec_result.metadata["price_source"],
        quality_notes=sec_result.quality_notes,
    )
    return export_excel_report(
        ROOT / "outputs" / "EquityLens_NDAQ_MVP.xlsx",
        COMPANY,
        data,
        ratios,
        trends,
        BASE_CASE,
        dcf_results,
        sensitivities,
        memo,
        source_data=sec_result.source_data,
        tags_used=sec_result.tags_used,
        quality_notes=sec_result.quality_notes,
        metadata=sec_result.metadata,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the SEC-grounded NDAQ EquityLens report.")
    parser.add_argument(
        "--share-price",
        type=float,
        help="Optional manual NDAQ price override or fallback when yfinance is unavailable.",
    )
    parser.add_argument("--years", type=int, default=7, choices=range(5, 11))
    args = parser.parse_args()
    try:
        result = build_report(args.share_price, args.years)
    except RuntimeError as exc:
        parser.error(str(exc))
    print(f"EquityLens report created: {result}")
