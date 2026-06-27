"""Interactive Streamlit dashboard for the EquityLens NDAQ MVP."""

from dataclasses import replace
import os
from pathlib import Path
import sys

import altair as alt
import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import BASE_CASE, COMPANY  # noqa: E402
from src.data_loader import load_financial_data  # noqa: E402
from src.dcf import run_dcf  # noqa: E402
from src.excel_export import export_excel_report  # noqa: E402
from src.financial_analysis import (  # noqa: E402
    calculate_financial_metrics,
    summarize_financial_trends,
)
from src.market_data import get_current_price  # noqa: E402
from src.memo import generate_investment_memo  # noqa: E402
from src.monte_carlo_dcf import (  # noqa: E402
    build_inputs_from_financials,
    create_histogram_data,
    create_percentile_summary_data,
    create_tornado_data,
    run_monte_carlo_dcf,
)
from src import sec_data as sec_data_module  # noqa: E402
from src.sensitivity import (  # noqa: E402
    revenue_margin_sensitivity,
    wacc_terminal_growth_sensitivity,
)

SECDataError = sec_data_module.SECDataError
SECDataResult = sec_data_module.SECDataResult
load_sec_financial_data = sec_data_module.load_sec_financial_data


st.set_page_config(
    page_title="EquityLens | NDAQ Valuation",
    page_icon="EL",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --navy: #14213d;
        --teal: #168f82;
        --cream: #f6f2e9;
        --ink: #202733;
    }
    .stApp {
        background:
            radial-gradient(circle at 90% 5%, rgba(22,143,130,.12), transparent 24rem),
            linear-gradient(180deg, #fbfaf6 0%, #f3efe6 100%);
        color: var(--ink);
    }
    h1, h2, h3 {
        color: var(--navy);
        font-family: Georgia, "Times New Roman", serif;
        letter-spacing: -0.025em;
    }
    [data-testid="stSidebar"] {
        background: #14213d;
    }
    [data-testid="stSidebar"] * {
        color: #f8f4eb;
    }
    [data-testid="stSidebar"] input {
        color: #14213d;
    }
    [data-testid="stMetric"] {
        background: rgba(255,255,255,.82);
        border: 1px solid rgba(20,33,61,.12);
        border-top: 4px solid var(--teal);
        border-radius: 4px;
        padding: 1rem 1.1rem;
        box-shadow: 0 12px 30px rgba(20,33,61,.06);
    }
    [data-testid="stMetric"] [data-testid="stMetricLabel"] p,
    [data-testid="stMetric"] [data-testid="stMetricValue"] *,
    [data-testid="stMetric"] [data-testid="stMetricDelta"] * {
        color: #14213d !important;
    }
    [data-testid="stMain"] p,
    [data-testid="stMain"] label,
    [data-testid="stMain"] li {
        color: #202733;
    }
    [data-testid="stAlert"] p,
    [data-testid="stAlert"] div {
        color: #202733 !important;
    }
    .ticker-chip {
        display: inline-block;
        color: #0d5f57;
        background: #dff3ef;
        border: 1px solid #a9d8d0;
        border-radius: 999px;
        padding: .25rem .7rem;
        font-weight: 700;
        letter-spacing: .08em;
        margin-bottom: .6rem;
    }
    .eyebrow {
        color: #168f82;
        font-size: .78rem;
        font-weight: 800;
        letter-spacing: .16em;
        text-transform: uppercase;
    }
    .memo-section {
        background: rgba(255,255,255,.72);
        border-left: 4px solid #168f82;
        padding: .85rem 1.1rem;
        margin: .65rem 0 1rem;
    }
    .small-note {
        color: #667085;
        font-size: .88rem;
    }
    div.stButton > button, div.stDownloadButton > button {
        background: #168f82;
        color: white;
        border: none;
        border-radius: 3px;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=60, show_spinner=False)
def load_market_price(ticker: str):
    """Briefly cache Yahoo price responses to avoid needless repeated calls."""
    return get_current_price(ticker)


def run_sec_connection_test() -> dict:
    """Call the SEC test helper safely, including with an older cached module."""
    tester = getattr(sec_data_module, "test_sec_connection", None)
    if tester is None:
        return {
            "ok": False,
            "message": "SEC connection helper is unavailable in the loaded module.",
            "status_code": None,
            "error": "Restart Streamlit so it reloads the current src/sec_data.py file.",
        }
    try:
        raw = tester(
            cache_path=ROOT / "data" / "cache" / "ndaq_companyfacts.json"
        )
    except Exception as exc:
        return {
            "ok": False,
            "message": "SEC connection test could not run.",
            "status_code": None,
            "error": str(exc),
        }
    return {
        **raw,
        "ok": bool(raw.get("ok", raw.get("success", False))),
        "message": raw.get("message")
        or ("SEC connection succeeded." if raw.get("success") else "SEC connection failed."),
        "status_code": raw.get("status_code", raw.get("http_status_code")),
        "error": raw.get("error", raw.get("error_message")),
    }


def load_sec_with_price_metadata(
    current_share_price: float,
    years: int,
    price_source: str,
    price_timestamp: str | None,
):
    """Support both the current SEC loader and older cached loader signatures."""
    common_arguments = {
        "current_share_price": current_share_price,
        "years": years,
        "cache_path": ROOT / "data" / "cache" / "ndaq_companyfacts.json",
    }
    try:
        return load_sec_financial_data(
            **common_arguments,
            price_source=price_source,
            price_timestamp=price_timestamp,
        )
    except TypeError as exc:
        message = str(exc)
        signature_mismatch = "unexpected keyword argument" in message and (
            "price_source" in message or "price_timestamp" in message
        )
        if not signature_mismatch:
            raise

    # A running Streamlit process may still hold the pre-price-metadata loader.
    result = load_sec_financial_data(**common_arguments)
    result.financials = result.financials.copy()
    result.financials["current_share_price"] = float(current_share_price)
    result.metadata = dict(result.metadata)
    result.metadata.update(
        {"price_source": price_source, "price_timestamp": price_timestamp}
    )
    if not result.quality_notes.empty and "metric" in result.quality_notes:
        result.quality_notes = result.quality_notes.copy()
        mask = result.quality_notes["metric"] == "current_share_price"
        result.quality_notes.loc[mask, "note"] = (
            f"Market price supplied by {price_source}; SEC Company Facts does not provide live prices."
            + (f" Price timestamp: {price_timestamp}." if price_timestamp else "")
        )
    return result


@st.cache_data
def load_sample_fallback(
    current_share_price: float,
    price_source: str,
    price_timestamp: str | None,
) -> SECDataResult:
    """Build a clearly labeled demo result when SEC data is unavailable."""
    financials = load_financial_data(ROOT / "data" / "ndaq_sample_financials.csv")
    financials = financials.copy()
    financials["current_share_price"] = float(current_share_price)
    financials["diluted_eps"] = float("nan")
    financials["source"] = "Local sample CSV fallback"
    fiscal_years = f"{financials['year'].min()}-{financials['year'].max()}"
    quality_notes = pd.DataFrame(
        [
            {
                "severity": "Warning",
                "metric": "data_source",
                "year": "All",
                "note": "SEC loading failed. All financial statement values are illustrative sample data.",
            },
            {
                "severity": "Info",
                "metric": "current_share_price",
                "year": int(financials["year"].max()),
                "note": f"Market price supplied by {price_source}."
                + (f" Price timestamp: {price_timestamp}." if price_timestamp else ""),
            },
        ]
    )
    tags_used = pd.DataFrame(
        [
            {
                "metric": "all financial fields",
                "taxonomy": "not applicable",
                "tag": "ndaq_sample_financials.csv",
                "unit": "USD millions",
                "method": "sample fallback",
                "fallback_rank": 1,
                "first_year": int(financials["year"].min()),
                "last_year": int(financials["year"].max()),
                "observations": len(financials),
            }
        ]
    )
    return SECDataResult(
        financials=financials,
        source_data=financials.copy(),
        tags_used=tags_used,
        quality_notes=quality_notes,
        metadata={
            "source": "Sample Data Fallback",
            "company": COMPANY.company_name,
            "ticker": COMPANY.ticker,
            "cik": "0001120193",
            "api_url": str(ROOT / "data" / "ndaq_sample_financials.csv"),
            "fiscal_years": fiscal_years,
            "years_included": financials["year"].tolist(),
            "from_cache": False,
            "price_source": price_source,
            "price_timestamp": price_timestamp,
            "is_sample_fallback": True,
        },
    )


@st.cache_data(ttl=3600)
def load_data(
    current_share_price: float,
    years: int,
    price_source: str,
    price_timestamp: str | None,
):
    """Load filing-grounded NDAQ data from SEC EDGAR."""
    return load_sec_with_price_metadata(
        current_share_price,
        years,
        price_source,
        price_timestamp,
    )


def valuation_conclusion(upside: float) -> str:
    """Translate implied return into the workbook's valuation labels."""
    if upside > 0.10:
        return "Undervalued"
    if upside < -0.10:
        return "Overvalued"
    return "Fairly valued"


def render_memo(memo: str) -> None:
    """Render each rule-based memo section as a readable card."""
    for block in memo.split("\n\n"):
        heading, body = block.split("\n", 1)
        st.markdown(f"### {heading}")
        st.markdown(f'<div class="memo-section">{body}</div>', unsafe_allow_html=True)


def format_sensitivity(table: pd.DataFrame) -> pd.DataFrame:
    """Create a presentation copy with readable percentage headers and dollar values."""
    display = table.copy()
    display.index = [f"{value:.1%}" for value in display.index]
    display.columns = [f"{value:.1%}" for value in display.columns]
    return display.map(lambda value: f"${value:.2f}")


def render_financial_chart(
    frame: pd.DataFrame,
    metric: str,
    title: str,
    color: str,
    unavailable_message: str,
    value_format: str,
) -> None:
    """Render a readable chart only when usable numeric observations exist."""
    if "year" not in frame.columns or metric not in frame.columns:
        st.warning(unavailable_message)
        return
    chart_data = frame[["year", metric]].copy()
    chart_data["year"] = pd.to_numeric(chart_data["year"], errors="coerce")
    chart_data[metric] = pd.to_numeric(chart_data[metric], errors="coerce")
    chart_data = chart_data.dropna().sort_values("year")
    if chart_data.empty:
        st.warning(unavailable_message)
        return
    chart_data = chart_data.rename(columns={metric: "value"})
    chart = (
        alt.Chart(chart_data)
        .mark_line(point=alt.OverlayMarkDef(filled=True, size=70), strokeWidth=3, color=color)
        .encode(
            x=alt.X("year:O", title="Fiscal year", sort=None),
            y=alt.Y("value:Q", title=title, axis=alt.Axis(format=value_format)),
            tooltip=[
                alt.Tooltip("year:O", title="Fiscal year"),
                alt.Tooltip("value:Q", title=title, format=value_format),
            ],
        )
        .properties(height=280)
        .configure(background="#fbfaf6")
        .configure_view(stroke="#d7dce5")
        .configure_axis(
            labelColor="#344054",
            titleColor="#14213d",
            domainColor="#98a2b3",
            tickColor="#98a2b3",
            gridColor="#e4e7ec",
        )
    )
    st.altair_chart(chart, use_container_width=True)


def render_monte_carlo_histogram(histogram_data: pd.DataFrame, current_price: float) -> None:
    """Render a simulation distribution from pre-binned values."""
    if histogram_data.empty:
        st.warning("Monte Carlo histogram is unavailable because no simulation values were produced.")
        return
    bars = (
        alt.Chart(histogram_data)
        .mark_bar(color="#168f82", opacity=0.78)
        .encode(
            x=alt.X("bin_midpoint:Q", title="Fair value per share", axis=alt.Axis(format="$,.0f")),
            y=alt.Y("count:Q", title="Simulation count"),
            tooltip=[
                alt.Tooltip("bin_start:Q", title="Bin start", format="$,.2f"),
                alt.Tooltip("bin_end:Q", title="Bin end", format="$,.2f"),
                alt.Tooltip("count:Q", title="Count", format=","),
            ],
        )
    )
    market_line = (
        alt.Chart(pd.DataFrame({"current_price": [current_price]}))
        .mark_rule(color="#d98255", strokeDash=[6, 4], strokeWidth=3)
        .encode(x="current_price:Q")
    )
    chart = (
        (bars + market_line)
        .properties(height=310)
        .configure(background="#fbfaf6")
        .configure_view(stroke="#d7dce5")
        .configure_axis(
            labelColor="#344054",
            titleColor="#14213d",
            domainColor="#98a2b3",
            tickColor="#98a2b3",
            gridColor="#e4e7ec",
        )
    )
    st.altair_chart(chart, use_container_width=True)


def render_percentile_chart(percentile_data: pd.DataFrame) -> None:
    """Render key fair-value percentiles."""
    if percentile_data.empty:
        st.warning("Percentile chart is unavailable because no Monte Carlo summary was produced.")
        return
    chart = (
        alt.Chart(percentile_data)
        .mark_bar(color="#14213d")
        .encode(
            x=alt.X("percentile:N", title="Percentile", sort=None),
            y=alt.Y(
                "fair_value_per_share:Q",
                title="Fair value per share",
                axis=alt.Axis(format="$,.0f"),
            ),
            tooltip=[
                alt.Tooltip("percentile:N", title="Percentile"),
                alt.Tooltip("fair_value_per_share:Q", title="Fair value", format="$,.2f"),
            ],
        )
        .properties(height=310)
        .configure(background="#fbfaf6")
        .configure_view(stroke="#d7dce5")
        .configure_axis(
            labelColor="#344054",
            titleColor="#14213d",
            domainColor="#98a2b3",
            tickColor="#98a2b3",
            gridColor="#e4e7ec",
        )
    )
    st.altair_chart(chart, use_container_width=True)


def render_tornado_chart(tornado_data: pd.DataFrame) -> None:
    """Render assumption correlations as a simple tornado-style chart."""
    if tornado_data.empty:
        st.warning("Monte Carlo sensitivity chart is unavailable because correlations could not be calculated.")
        return
    if "assumption" in tornado_data.columns:
        y_column = "assumption:N"
        x_column = "correlation_with_fair_value:Q"
        x_title = "Correlation with fair value"
        tooltip_value = "correlation_with_fair_value:Q"
        tooltip_title = "Correlation"
    else:
        y_column = "value_driver:N"
        x_column = "valuation_impact_score:Q"
        x_title = "Valuation impact score"
        tooltip_value = "valuation_impact_score:Q"
        tooltip_title = "Impact score"
    chart = (
        alt.Chart(tornado_data)
        .mark_bar(color="#d98255")
        .encode(
            x=alt.X(
                x_column,
                title=x_title,
                axis=alt.Axis(format=".2f"),
            ),
            y=alt.Y(y_column, title="Assumption", sort=None),
            tooltip=[
                alt.Tooltip(y_column, title="Assumption"),
                alt.Tooltip(
                    tooltip_value,
                    title=tooltip_title,
                    format=".2f",
                ),
            ],
        )
        .properties(height=270)
        .configure(background="#fbfaf6")
        .configure_view(stroke="#d7dce5")
        .configure_axis(
            labelColor="#344054",
            titleColor="#14213d",
            domainColor="#98a2b3",
            tickColor="#98a2b3",
            gridColor="#e4e7ec",
        )
    )
    st.altair_chart(chart, use_container_width=True)


def metric_health(
    financials: pd.DataFrame, quality_notes: pd.DataFrame
) -> dict[str, str]:
    """Summarize whether the most important model inputs are usable."""
    def available(column: str) -> bool:
        return column in financials and pd.to_numeric(
            financials[column], errors="coerce"
        ).notna().any()

    fcf_status = "missing"
    if available("free_cash_flow"):
        fcf_notes = (
            quality_notes[quality_notes["metric"] == "free_cash_flow"]
            if not quality_notes.empty and "metric" in quality_notes.columns
            else pd.DataFrame()
        )
        fcf_status = "calculated" if not fcf_notes.empty else "available"

    debt_status = "missing"
    if available("total_debt"):
        debt_notes = (
            quality_notes[
                quality_notes["metric"].isin(
                    ["total_debt", "debt_current", "debt_noncurrent"]
                )
            ]
            if not quality_notes.empty and "metric" in quality_notes.columns
            else pd.DataFrame()
        )
        debt_status = "estimated" if not debt_notes.empty else "available"

    return {
        "Revenue": "available" if available("revenue") else "missing",
        "EBIT": "available" if available("ebit") else "missing",
        "FCF": fcf_status,
        "Debt": debt_status,
        "Shares": "available" if available("diluted_shares") else "missing",
    }


with st.sidebar:
    st.markdown("## Data source")
    st.success("Preferred: SEC Filing Data")
    use_sample_fallback = st.toggle("Use Sample Data Fallback", value=True)
    if st.button("Test SEC Connection"):
        connection = run_sec_connection_test()
        if connection["ok"]:
            st.success(
                f"{connection['message']} (HTTP {connection['status_code']})."
            )
        else:
            st.warning(connection["message"])
            st.code(connection["error"] or "No diagnostic message returned.")
        with st.expander("SEC connection diagnostics"):
            st.json(connection)
    auto_fetch_price = st.toggle("Auto-fetch market price", value=True)
    default_price = float(os.getenv("NDAQ_SHARE_PRICE", "0") or 0)
    market_result = None
    price_source = "manual input"
    price_timestamp = None
    if auto_fetch_price:
        market_result = load_market_price(COMPANY.ticker)
        if market_result["current_price"] is not None:
            current_share_price = float(market_result["current_price"])
            price_source = "yfinance"
            price_timestamp = market_result["price_timestamp"]
            st.success(f"NDAQ price: ${current_share_price:.2f}")
            if price_timestamp:
                st.caption(f"Last available: {price_timestamp}")
        else:
            st.warning(market_result["error_message"] or "Automatic price fetch failed.")
            current_share_price = st.number_input(
                "Manual NDAQ share price",
                min_value=0.0,
                value=default_price,
                step=0.50,
                help="Fallback used when yfinance is unavailable.",
            )
    else:
        current_share_price = st.number_input(
            "Manual NDAQ share price",
            min_value=0.0,
            value=default_price,
            step=0.50,
            help="Manual fallback. SEC filings do not provide live share prices.",
        )
    history_years = st.slider("Fiscal years", 5, 10, 7)
    st.caption("Financial statement values come only from SEC EDGAR Company Facts.")
    st.divider()
    st.markdown("## Valuation controls")
    st.caption("Adjust the assumptions and EquityLens recalculates instantly.")
    revenue_growth = st.slider(
        "Revenue growth", 0.0, 15.0, BASE_CASE.revenue_growth * 100, 0.5, format="%.1f%%"
    ) / 100
    ebit_margin = st.slider(
        "EBIT margin", 15.0, 40.0, BASE_CASE.ebit_margin * 100, 0.5, format="%.1f%%"
    ) / 100
    tax_rate = st.slider(
        "Tax rate", 10.0, 35.0, BASE_CASE.tax_rate * 100, 0.5, format="%.1f%%"
    ) / 100
    wacc = st.slider(
        "WACC", 5.0, 14.0, BASE_CASE.wacc * 100, 0.5, format="%.1f%%"
    ) / 100
    terminal_growth = st.slider(
        "Terminal growth", 0.0, 5.0, BASE_CASE.terminal_growth * 100, 0.5, format="%.1f%%"
    ) / 100
    capex_pct_revenue = st.slider(
        "Capex / revenue", 1.0, 8.0, BASE_CASE.capex_pct_revenue * 100, 0.5, format="%.1f%%"
    ) / 100
    st.divider()
    st.markdown("## Monte Carlo")
    run_simulation = st.toggle("Run Monte Carlo simulation", value=True)
    simulation_count = st.slider(
        "Simulations",
        min_value=1_000,
        max_value=20_000,
        value=5_000,
        step=1_000,
        help="Higher counts produce smoother output but take longer to calculate.",
    )
    random_seed = st.number_input(
        "Random seed",
        min_value=0,
        value=42,
        step=1,
        help="Keep this fixed for reproducible results.",
    )
    st.caption("Uses simple Python/numpy distributions; no Argo or paid API dependency.")
    st.divider()
    st.caption("Replace SEC_USER_AGENT with a genuine project contact before deployment.")

if current_share_price <= 0:
    st.info("Enter a current NDAQ share price in the sidebar to load SEC filing data and run the valuation.")
    st.stop()

try:
    sec_result = load_data(current_share_price, history_years, price_source, price_timestamp)
except SECDataError as exc:
    st.warning("SEC filing data could not be loaded.")
    st.code(str(exc))
    if use_sample_fallback:
        st.warning("EquityLens is continuing with illustrative sample data.")
        sec_result = load_sample_fallback(current_share_price, price_source, price_timestamp)
    else:
        st.caption("Enable Use Sample Data Fallback to continue without SEC data.")
        st.stop()
except Exception as exc:
    st.warning("EquityLens could not prepare the SEC dataset.")
    st.code(str(exc))
    if use_sample_fallback:
        st.warning("EquityLens is continuing with illustrative sample data.")
        sec_result = load_sample_fallback(current_share_price, price_source, price_timestamp)
    else:
        st.caption("Enable Use Sample Data Fallback to continue without SEC data.")
        st.stop()

required_financial_columns = [
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
data = sec_result.financials.copy()
additional_quality_notes = []
for column_name in required_financial_columns:
    if column_name not in data.columns:
        data[column_name] = float("nan")
        additional_quality_notes.append(
            {
                "severity": "Warning",
                "metric": column_name,
                "year": "All",
                "note": "The field was not returned by the data loader; an empty numeric column was added.",
            }
        )
    data[column_name] = pd.to_numeric(data[column_name], errors="coerce")

missing_fcf = (
    data["free_cash_flow"].isna()
    & data["operating_cash_flow"].notna()
    & data["capex"].notna()
)
data.loc[missing_fcf, "free_cash_flow"] = (
    data.loc[missing_fcf, "operating_cash_flow"]
    - data.loc[missing_fcf, "capex"].abs()
)
for fiscal_year in data.loc[missing_fcf, "year"].dropna().tolist():
    additional_quality_notes.append(
        {
            "severity": "Info",
            "metric": "free_cash_flow",
            "year": int(fiscal_year),
            "note": "Filled missing free cash flow as operating cash flow minus absolute capex.",
        }
    )

for column_name in required_financial_columns[1:-1]:
    if data[column_name].notna().sum() == 0:
        additional_quality_notes.append(
            {
                "severity": "Warning",
                "metric": column_name,
                "year": "All",
                "note": "No usable numeric observations were extracted for this field.",
            }
        )

if additional_quality_notes:
    sec_result.quality_notes = (
        pd.concat(
            [sec_result.quality_notes, pd.DataFrame(additional_quality_notes)],
            ignore_index=True,
        )
        .drop_duplicates()
        .reset_index(drop=True)
    )
sec_result.financials = data
metrics = calculate_financial_metrics(data)
trends = summarize_financial_trends(metrics)

assumptions = replace(
    BASE_CASE,
    revenue_growth=revenue_growth,
    ebit_margin=ebit_margin,
    tax_rate=tax_rate,
    wacc=wacc,
    terminal_growth=terminal_growth,
    capex_pct_revenue=capex_pct_revenue,
)

if assumptions.wacc <= assumptions.terminal_growth:
    st.error("WACC must be greater than terminal growth. Increase WACC or reduce terminal growth.")
    st.stop()

dcf_results = run_dcf(data, assumptions)
sensitivities = {
    "wacc_terminal_growth": wacc_terminal_growth_sensitivity(data, assumptions),
    "revenue_growth_ebit_margin": revenue_margin_sensitivity(data, assumptions),
}
monte_carlo_outputs = None
if run_simulation:
    try:
        monte_carlo_inputs = build_inputs_from_financials(
            data,
            ticker=COMPANY.ticker,
            company_name=COMPANY.company_name,
            current_price=dcf_results["current_share_price"],
            base_case_fair_value=dcf_results["fair_value_per_share"],
            forecast_years=assumptions.forecast_years,
            simulations=int(simulation_count),
            random_seed=int(random_seed),
            historical_financials=data,
            base_assumptions=assumptions,
        )
        monte_carlo_result = run_monte_carlo_dcf(monte_carlo_inputs)
        simulation_df = monte_carlo_result.simulation_df
        monte_carlo_summary = monte_carlo_result.summary
        monte_carlo_sensitivity = monte_carlo_result.sensitivity
        monte_carlo_outputs = {
            "simulation_df": simulation_df,
            "summary": monte_carlo_summary,
            "sensitivity": monte_carlo_sensitivity,
            "value_driver_table": monte_carlo_result.value_driver_table,
            "explanation": monte_carlo_result.explanation,
            "histogram": create_histogram_data(simulation_df),
            "percentiles": create_percentile_summary_data(monte_carlo_summary),
            "tornado": create_tornado_data(monte_carlo_result.value_driver_table),
        }
    except Exception as exc:
        st.warning("Monte Carlo simulation could not be completed.")
        st.code(
            "Function failed: run_monte_carlo_dcf(inputs)\n"
            f"Error: {exc}\n\n"
            "Fix guidance: build a MonteCarloDCFInputs object with ticker, company_name, "
            "latest_revenue, current_price, cash, debt, diluted_shares, simulations, "
            "distributions, and optional historical_financials/base_assumptions. "
            "Do not pass historical_financials as a separate keyword argument."
        )
memo = generate_investment_memo(
    trends,
    dcf_results,
    sensitivities,
    data_source=sec_result.metadata["source"],
    price_source=sec_result.metadata["price_source"],
    quality_notes=sec_result.quality_notes,
)
conclusion = valuation_conclusion(dcf_results["upside_downside"])

st.markdown('<div class="eyebrow">Financial analysis / DCF valuation</div>', unsafe_allow_html=True)
st.markdown(f'<div class="ticker-chip">{COMPANY.ticker}</div>', unsafe_allow_html=True)
st.title("EquityLens")
st.markdown(
    f"### {COMPANY.company_name}"
    "\nA transparent, assumption-driven view of historical performance and intrinsic value."
)
if sec_result.metadata.get("is_sample_fallback"):
    st.warning("SAMPLE DATA MODE: financial statement values are illustrative and are not SEC filing facts.")
else:
    st.markdown(
        '<p class="small-note">Financial statement inputs are drawn from SEC 10-K XBRL facts. Market price comes from yfinance when available, with a manual fallback. This is not investment advice.</p>',
        unsafe_allow_html=True,
    )

st.header("Data Source")
source_columns = st.columns(4)
source_columns[0].metric("Source", sec_result.metadata["source"])
source_columns[1].metric("Ticker / CIK", f"NDAQ / {sec_result.metadata['cik']}")
source_columns[2].metric("Fiscal years", sec_result.metadata["fiscal_years"])
source_columns[3].metric("Source observations", f"{len(sec_result.source_data):,}")
st.caption(sec_result.metadata["api_url"])
with st.expander("Missing fields and fallback calculations"):
    if sec_result.quality_notes.empty:
        st.write("No data-quality exceptions were identified.")
    else:
        quality_notes_display = sec_result.quality_notes.copy()
        if "year" in quality_notes_display.columns:
            quality_notes_display["year"] = quality_notes_display["year"].astype(str)
        st.dataframe(quality_notes_display, use_container_width=True, hide_index=True)

st.header("Data Health Score")
health_columns = st.columns(5)
for health_column, (health_label, health_status) in zip(
    health_columns, metric_health(data, sec_result.quality_notes).items()
):
    health_column.metric(health_label, health_status.title())
st.caption(
    "Available means usable SEC observations were found. Calculated or estimated means EquityLens applied a documented filing-based fallback."
)

st.header("SEC Data Debug")
with st.expander("Inspect SEC extraction and clean model data"):
    st.subheader("Raw SEC extracted rows")
    if sec_result.source_data.empty:
        st.warning("No raw SEC source observations are available for inspection.")
    else:
        st.dataframe(sec_result.source_data, use_container_width=True, hide_index=True)

    st.subheader("Clean financials DataFrame")
    st.dataframe(
        data[required_financial_columns], use_container_width=True, hide_index=True
    )

    debug_left, debug_right = st.columns(2)
    with debug_left:
        st.markdown("**DataFrame column names**")
        st.code("\n".join(data.columns.astype(str).tolist()))
        st.markdown("**Data types**")
        st.dataframe(
            pd.DataFrame(
                {
                    "column": data.columns,
                    "dtype": [str(dtype) for dtype in data.dtypes],
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
    with debug_right:
        st.markdown("**Non-null values by column**")
        st.dataframe(
            data.notna()
            .sum()
            .rename("non_null_count")
            .reset_index()
            .rename(columns={"index": "column"}),
            use_container_width=True,
            hide_index=True,
        )
        included_years = (
            pd.to_numeric(data["year"], errors="coerce").dropna().astype(int).tolist()
        )
        st.markdown(f"**Years included:** {', '.join(map(str, included_years)) or 'None'}")
        debug_metrics = required_financial_columns[1:-1]
        successful_metrics = [
            metric
            for metric in debug_metrics
            if pd.to_numeric(data[metric], errors="coerce").notna().any()
        ]
        missing_metrics = [
            metric for metric in debug_metrics if metric not in successful_metrics
        ]
        st.markdown(
            "**Metrics successfully extracted:** "
            + (", ".join(successful_metrics) or "None")
        )
        st.markdown(
            "**Metrics missing:** " + (", ".join(missing_metrics) or "None")
        )

metric_columns = st.columns(4)
metric_columns[0].metric("Current share price", f"${dcf_results['current_share_price']:.2f}")
metric_columns[1].metric("Base fair value", f"${dcf_results['fair_value_per_share']:.2f}")
metric_columns[2].metric(
    "Implied upside / downside",
    f"{dcf_results['upside_downside']:.1%}",
    delta=f"${dcf_results['fair_value_per_share'] - dcf_results['current_share_price']:.2f} / share",
)
metric_columns[3].metric("Valuation conclusion", conclusion)
price_detail = f"Price source: {sec_result.metadata['price_source']}"
if sec_result.metadata.get("price_timestamp"):
    price_detail += f" | Last available: {sec_result.metadata['price_timestamp']}"
st.caption(price_detail)
if sec_result.metadata["price_source"] == "yfinance":
    st.warning("yfinance prices may be delayed or reflect the latest available close rather than a real-time exchange quote.")
elif market_result and market_result.get("error_message"):
    st.warning("Automatic market-price retrieval failed; the valuation is using the manual fallback.")

st.divider()
st.header("Historical performance")
chart_columns = st.columns(3)
with chart_columns[0]:
    st.subheader("Revenue")
    render_financial_chart(
        data,
        "revenue",
        "Revenue ($mm)",
        "#168f82",
        "Revenue chart unavailable because revenue data was not extracted from SEC facts.",
        "$,.0f",
    )
with chart_columns[1]:
    st.subheader("EBIT margin")
    render_financial_chart(
        metrics,
        "ebit_margin",
        "EBIT margin",
        "#14213d",
        "EBIT margin chart unavailable because revenue or EBIT data was not extracted from SEC facts.",
        ".1%",
    )
with chart_columns[2]:
    st.subheader("Free cash flow")
    render_financial_chart(
        data,
        "free_cash_flow",
        "Free cash flow ($mm)",
        "#d98255",
        "Free cash flow chart unavailable because operating cash flow or capex was not extracted from SEC facts.",
        "$,.0f",
    )

with st.expander("Clean Financials Table"):
    st.dataframe(
        data[required_financial_columns], use_container_width=True, hide_index=True
    )
with st.expander("Ratio Analysis Table"):
    st.dataframe(metrics, use_container_width=True, hide_index=True)
with st.expander("SEC Tags Used Table"):
    if sec_result.tags_used.empty:
        st.warning("No SEC tag selections are available for this dataset.")
    else:
        st.dataframe(sec_result.tags_used, use_container_width=True, hide_index=True)

st.divider()
st.header("DCF outlook")
forecast = dcf_results["projections"][["year", "revenue", "ebit", "unlevered_fcf", "pv_fcf"]].copy()
forecast.columns = ["Year", "Revenue", "EBIT", "Unlevered FCF", "PV of FCF"]
forecast["Year"] = forecast["Year"].map(lambda value: f"{value:.0f}")
for column_name in ["Revenue", "EBIT", "Unlevered FCF", "PV of FCF"]:
    forecast[column_name] = forecast[column_name].map(lambda value: f"${value:,.0f}")
st.dataframe(
    forecast,
    use_container_width=True,
    hide_index=True,
)

if monte_carlo_outputs:
    st.divider()
    st.header("Monte Carlo valuation")
    st.caption(
        "This simulation does not replace the base DCF. It shows how uncertainty in the key assumptions changes fair value per share."
    )
    mc_summary = monte_carlo_outputs["summary"]
    mc_columns = st.columns(4)
    mc_columns[0].metric("Median fair value", f"${mc_summary['median_fair_value']:.2f}")
    mc_columns[1].metric("Mean fair value", f"${mc_summary['mean_fair_value']:.2f}")
    mc_columns[2].metric(
        "Probability above price",
        f"{mc_summary['probability_above_current_price']:.1%}",
    )
    mc_columns[3].metric("Simulation view", mc_summary["valuation_label"])
    st.caption(mc_summary["confidence_note"])
    st.info(mc_summary["probability_context"])
    if mc_summary.get("historical_financials_warning"):
        st.warning(mc_summary["historical_financials_warning"])

    mc_chart_left, mc_chart_right = st.columns(2)
    with mc_chart_left:
        st.subheader("Fair value distribution")
        render_monte_carlo_histogram(
            monte_carlo_outputs["histogram"], mc_summary["current_price"]
        )
    with mc_chart_right:
        st.subheader("Percentile summary")
        render_percentile_chart(monte_carlo_outputs["percentiles"])

    st.subheader("Key value-driver priority")
    render_tornado_chart(monte_carlo_outputs["tornado"])
    st.subheader("Simulation explanation")
    st.write(monte_carlo_outputs["explanation"])
    with st.expander("Monte Carlo Value Driver Table"):
        st.dataframe(
            monte_carlo_outputs["value_driver_table"],
            use_container_width=True,
            hide_index=True,
        )
    with st.expander("Monte Carlo Summary Table"):
        summary_table = pd.DataFrame(
            [{"metric": key, "value": value} for key, value in mc_summary.items()]
        )
        summary_table["value"] = summary_table["value"].astype(str)
        st.dataframe(summary_table, use_container_width=True, hide_index=True)
    with st.expander("Monte Carlo Simulation Results"):
        st.dataframe(
            monte_carlo_outputs["simulation_df"],
            use_container_width=True,
            hide_index=True,
        )
    with st.expander("Monte Carlo Assumption Correlations"):
        st.dataframe(
            monte_carlo_outputs["sensitivity"],
            use_container_width=True,
            hide_index=True,
        )

st.divider()
st.header("Sensitivity analysis")
left, right = st.columns(2)
with left:
    st.subheader("WACC vs. terminal growth")
    st.dataframe(
        format_sensitivity(sensitivities["wacc_terminal_growth"]),
        use_container_width=True,
    )
with right:
    st.subheader("Revenue growth vs. EBIT margin")
    st.dataframe(
        format_sensitivity(sensitivities["revenue_growth_ebit_margin"]),
        use_container_width=True,
    )

st.divider()
st.header("Investment memo")
render_memo(memo)

st.divider()
st.header("Export the analysis")
st.write("Prepare an Excel workbook using the assumptions currently selected in the sidebar.")
if st.button("Prepare Excel report", type="primary"):
    export_path = export_excel_report(
        ROOT / "outputs" / "EquityLens_NDAQ_Streamlit.xlsx",
        COMPANY,
        data,
        metrics,
        trends,
        assumptions,
        dcf_results,
        sensitivities,
        memo,
        source_data=sec_result.source_data,
        tags_used=sec_result.tags_used,
        quality_notes=sec_result.quality_notes,
        metadata=sec_result.metadata,
        monte_carlo=monte_carlo_outputs,
    )
    st.session_state["excel_bytes"] = export_path.read_bytes()

if "excel_bytes" in st.session_state:
    st.download_button(
        "Download Excel report",
        data=st.session_state["excel_bytes"],
        file_name="EquityLens_NDAQ.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
