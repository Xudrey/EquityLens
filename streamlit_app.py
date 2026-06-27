"""Focused Streamlit MVP for EquityLens."""

from dataclasses import replace
from pathlib import Path
import os
import sys

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import BASE_CASE, COMPANY
from src.data_loader import load_financial_data
from src.dcf import run_dcf
from src.excel_export import export_excel_report
from src.financial_analysis import calculate_financial_metrics, summarize_financial_trends
from src.market_data import get_current_price
from src.memo import generate_investment_memo, valuation_conclusion
from src.sec_data import FinancialDataResult, SECDataError, load_sec_financial_data
from src.sensitivity import revenue_margin_sensitivity, wacc_terminal_growth_sensitivity

st.set_page_config(page_title="EquityLens | NDAQ MVP", page_icon="EL", layout="wide")

st.markdown(
    """
    <style>
    .stApp {background: linear-gradient(180deg, #fbfaf6 0%, #f1ede3 100%); color: #202733;}
    h1, h2, h3 {color: #14213d; font-family: Georgia, 'Times New Roman', serif;}
    [data-testid="stSidebar"] {background: #14213d;}
    [data-testid="stSidebar"] * {color: #f8f4eb;}
    [data-testid="stSidebar"] input {color: #14213d;}
    [data-testid="stMetric"] {background: rgba(255,255,255,.88); border-left: 4px solid #168f82; border-radius: 5px; padding: 1rem; box-shadow: 0 10px 24px rgba(20,33,61,.06);}
    [data-testid="stMetric"] * {color: #14213d !important;}
    .hero {background: #ffffffcc; border: 1px solid #d7dce5; border-radius: 10px; padding: 1.2rem 1.4rem;}
    .insight {background: #dff3ef; border-left: 5px solid #168f82; border-radius: 6px; padding: 1rem 1.2rem; color: #14213d;}
    .driver-card {background: #ffffffd9; border: 1px solid #d7dce5; border-radius: 8px; padding: .9rem 1rem; height: 100%;}
    .warning-card {background: #fff4df; border-left: 5px solid #d98255; padding: 1rem 1.2rem; border-radius: 6px;}
    .memo-section {background: #ffffffcc; border-left: 4px solid #168f82; padding: .8rem 1rem; margin-bottom: .8rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

KEY_VALUE_DRIVERS = [
    {"driver": "Recurring revenue growth", "why": "Nasdaq has data, index, workflow, and technology revenue streams that can be more recurring than transaction revenue.", "valuation_effect": "Higher durable growth increases forecast cash flows."},
    {"driver": "Operating margin stability", "why": "Margins show whether scale benefits, integration costs, and competition are being managed well.", "valuation_effect": "Higher margins turn more revenue into EBIT and free cash flow."},
    {"driver": "Free cash flow conversion", "why": "Cash generation matters more than accounting earnings in a DCF.", "valuation_effect": "Better conversion increases the cash flows being discounted."},
    {"driver": "Debt and acquisition integration risk", "why": "Leverage and integration costs can absorb cash and increase risk.", "valuation_effect": "More debt reduces equity value after enterprise value is calculated."},
    {"driver": "Market data / financial technology growth", "why": "These areas can support growth outside traditional exchange transaction volumes.", "valuation_effect": "A stronger mix can support growth and margin durability."},
    {"driver": "WACC and interest-rate environment", "why": "The discount rate reflects market risk, rates, and leverage.", "valuation_effect": "A higher WACC lowers the present value of future cash flows."},
    {"driver": "Terminal growth assumption", "why": "Terminal value often represents a large part of a DCF.", "valuation_effect": "Small terminal-growth changes can materially change fair value."},
]


def build_sample_result(current_share_price: float) -> FinancialDataResult:
    data = load_financial_data(ROOT / "data" / "ndaq_sample_financials.csv").copy()
    data["current_share_price"] = float(current_share_price)
    return FinancialDataResult(
        financials=data,
        source_data=data.copy(),
        tags_used=pd.DataFrame([{"metric": "all fields", "tag": "ndaq_sample_financials.csv", "method": "illustrative sample fallback"}]),
        quality_notes=pd.DataFrame([{"severity": "Warning", "metric": "data_source", "note": "Sample fallback data is illustrative and should not be used as filing-grounded financial data."}]),
        metadata={
            "source": "Sample Data Fallback",
            "company": COMPANY.company_name,
            "ticker": COMPANY.ticker,
            "cik": COMPANY.cik,
            "api_url": str(ROOT / "data" / "ndaq_sample_financials.csv"),
            "fiscal_years": f"{int(data['year'].min())}-{int(data['year'].max())}",
            "is_sample_fallback": True,
        },
    )


@st.cache_data(ttl=60, show_spinner=False)
def load_market_price(ticker: str) -> dict:
    return get_current_price(ticker)


@st.cache_data(ttl=1800, show_spinner=False)
def load_sec_data_cached(current_share_price: float, years: int) -> FinancialDataResult:
    return load_sec_financial_data(current_share_price=current_share_price, years=years, cache_path=ROOT / "data" / "cache" / "ndaq_companyfacts.json")


def format_sensitivity(table: pd.DataFrame) -> pd.DataFrame:
    display = table.copy()
    display.index = [f"{value:.1%}" for value in display.index]
    display.columns = [f"{value:.1%}" for value in display.columns]
    return display.map(lambda value: f"${value:.2f}")


def line_chart(frame: pd.DataFrame, y_column: str, title: str, value_format: str = ",.0f") -> None:
    chart_data = frame[["year", y_column]].copy()
    chart_data[y_column] = pd.to_numeric(chart_data[y_column], errors="coerce")
    chart_data = chart_data.dropna()
    if chart_data.empty:
        st.warning(f"{title} chart unavailable for the selected data.")
        return
    chart = (
        alt.Chart(chart_data)
        .mark_line(point=True, strokeWidth=3, color="#168f82")
        .encode(
            x=alt.X("year:O", title="Fiscal year"),
            y=alt.Y(f"{y_column}:Q", title=title, axis=alt.Axis(format=value_format)),
            tooltip=["year", alt.Tooltip(f"{y_column}:Q", title=title, format=value_format)],
        )
        .properties(height=260)
    )
    st.altair_chart(chart, use_container_width=True)


def so_what_text(trends: dict, dcf_results: dict, sensitivities: dict[str, pd.DataFrame]) -> str:
    conclusion = valuation_conclusion(dcf_results["upside_downside"])
    wacc_range = sensitivities["wacc_terminal_growth"].max().max() - sensitivities["wacc_terminal_growth"].min().min()
    operating_range = sensitivities["revenue_growth_ebit_margin"].max().max() - sensitivities["revenue_growth_ebit_margin"].min().min()
    key_assumption = "WACC and terminal growth" if wacc_range >= operating_range else "revenue growth and EBIT margin"
    return (
        f"Revenue has {trends['revenue_trend']} across the selected period, while EBIT margin has {trends['margin_trend']}. "
        f"Free cash flow is {trends['fcf_trend']}. Based on the current assumptions, the DCF labels NDAQ as {conclusion}. "
        f"The most important sensitivity area in this setup appears to be {key_assumption}."
    )


def render_memo(memo: str) -> None:
    for block in memo.split("\n\n"):
        title, body = block.split("\n", 1)
        st.markdown(f"### {title}")
        st.markdown(f"<div class='memo-section'>{body}</div>", unsafe_allow_html=True)


with st.sidebar:
    st.header("Inputs")
    data_mode = st.radio("Data mode", ["SEC Filing Data", "Sample Data Fallback"], index=0)
    use_sample_fallback = st.toggle("Use sample fallback if SEC fails", value=True)
    auto_fetch = st.toggle("Auto-fetch market price", value=True)
    default_price = float(os.getenv("NDAQ_SHARE_PRICE", "90") or 90)
    price_source = "manual input"
    price_timestamp = None
    if auto_fetch:
        price_result = load_market_price(COMPANY.ticker)
        if price_result["current_price"] is not None:
            current_share_price = float(price_result["current_price"])
            price_source = price_result["price_source"]
            price_timestamp = price_result["price_timestamp"]
            st.success(f"NDAQ price: ${current_share_price:.2f}")
        else:
            st.warning("Market price could not be auto-fetched. Please enter the current share price manually.")
            current_share_price = st.number_input("Manual NDAQ share price", min_value=0.0, value=default_price, step=0.50)
    else:
        current_share_price = st.number_input("Manual NDAQ share price", min_value=0.0, value=default_price, step=0.50)
    years = st.slider("Fiscal years", 5, 10, 7)
    st.divider()
    st.header("DCF assumptions")
    revenue_growth = st.slider("Revenue growth", 0.0, 15.0, BASE_CASE.revenue_growth * 100, 0.5, format="%.1f%%") / 100
    ebit_margin = st.slider("EBIT margin", 15.0, 40.0, BASE_CASE.ebit_margin * 100, 0.5, format="%.1f%%") / 100
    tax_rate = st.slider("Tax rate", 10.0, 35.0, BASE_CASE.tax_rate * 100, 0.5, format="%.1f%%") / 100
    wacc = st.slider("WACC", 5.0, 14.0, BASE_CASE.wacc * 100, 0.5, format="%.1f%%") / 100
    terminal_growth = st.slider("Terminal growth", 0.0, 5.0, BASE_CASE.terminal_growth * 100, 0.5, format="%.1f%%") / 100
    capex_pct_revenue = st.slider("Capex / revenue", 1.0, 8.0, BASE_CASE.capex_pct_revenue * 100, 0.5, format="%.1f%%") / 100

if current_share_price <= 0:
    st.info("Enter a current NDAQ share price in the sidebar to run the valuation.")
    st.stop()

if data_mode == "Sample Data Fallback":
    data_result = build_sample_result(current_share_price)
else:
    try:
        data_result = load_sec_data_cached(current_share_price, years)
    except SECDataError as exc:
        if use_sample_fallback:
            st.warning("SEC filing data could not be loaded. EquityLens is using sample data fallback so the workflow remains usable.")
            data_result = build_sample_result(current_share_price)
            data_result.quality_notes = pd.concat([data_result.quality_notes, pd.DataFrame([{"severity": "Warning", "metric": "sec_error", "note": str(exc)}])], ignore_index=True)
        else:
            st.warning("SEC filing data could not be loaded. Enable sample fallback to continue.")
            st.stop()

data = data_result.financials.copy()
data["current_share_price"] = current_share_price
metrics = calculate_financial_metrics(data)
trends = summarize_financial_trends(metrics)
assumptions = replace(BASE_CASE, revenue_growth=revenue_growth, ebit_margin=ebit_margin, tax_rate=tax_rate, wacc=wacc, terminal_growth=terminal_growth, capex_pct_revenue=capex_pct_revenue)
if assumptions.wacc <= assumptions.terminal_growth:
    st.error("WACC must be greater than terminal growth. Increase WACC or reduce terminal growth.")
    st.stop()
dcf_results = run_dcf(data, assumptions)
sensitivities = {"wacc_terminal_growth": wacc_terminal_growth_sensitivity(data, assumptions), "revenue_growth_ebit_margin": revenue_margin_sensitivity(data, assumptions)}
memo = generate_investment_memo(trends, dcf_results, sensitivities, data_source=data_result.metadata["source"], price_source=price_source, key_drivers=KEY_VALUE_DRIVERS)
conclusion = valuation_conclusion(dcf_results["upside_downside"])

st.markdown("<div class='hero'>", unsafe_allow_html=True)
st.title("EquityLens")
st.subheader("AI-assisted financial analysis and valuation dashboard for Nasdaq, Inc. (NDAQ)")
st.write("This tool converts public company financial data into a structured valuation view, helping users understand financial trends, DCF assumptions, valuation sensitivity, and key value drivers.")
st.warning("For educational and research purposes only. Not investment advice.")
st.markdown("</div>", unsafe_allow_html=True)

st.header("What this tool does")
st.markdown(
    """
- Loads Nasdaq financial data from SEC filing data when available, with sample fallback
- Analyzes revenue, EBIT, net income, free cash flow, debt, and shares
- Calculates key financial ratios
- Runs a simple DCF valuation
- Shows sensitivity to assumptions like WACC, terminal growth, revenue growth, and EBIT margin
- Generates a memo-style interpretation of the results
"""
)

st.header("So What?")
st.markdown(f"<div class='insight'>{so_what_text(trends, dcf_results, sensitivities)}</div>", unsafe_allow_html=True)

st.header("Dashboard")
cols = st.columns(4)
cols[0].metric("Current share price", f"${dcf_results['current_share_price']:.2f}")
cols[1].metric("DCF fair value", f"${dcf_results['fair_value_per_share']:.2f}")
cols[2].metric("Implied upside/downside", f"{dcf_results['upside_downside']:.1%}")
cols[3].metric("Scenario label", conclusion.title())
st.caption(f"Data source: {data_result.metadata['source']} | Price source: {price_source}" + (f" | Price timestamp: {price_timestamp}" if price_timestamp else ""))
if data_result.metadata.get("is_sample_fallback"):
    st.warning("Sample Data Fallback: financial statement values are illustrative and are not SEC filing facts.")

st.header("Historical financial trends")
chart_cols = st.columns(3)
with chart_cols[0]:
    st.subheader("Revenue")
    line_chart(data, "revenue", "Revenue ($mm)", "$,.0f")
with chart_cols[1]:
    st.subheader("EBIT margin")
    line_chart(metrics, "ebit_margin", "EBIT margin", ".1%")
with chart_cols[2]:
    st.subheader("Free cash flow")
    line_chart(data, "free_cash_flow", "Free cash flow ($mm)", "$,.0f")
with st.expander("View financial and ratio tables"):
    st.dataframe(data, use_container_width=True, hide_index=True)
    st.dataframe(metrics, use_container_width=True, hide_index=True)

st.header("Key Value Drivers for Nasdaq")
driver_cols = st.columns(2)
for idx, driver in enumerate(KEY_VALUE_DRIVERS):
    with driver_cols[idx % 2]:
        st.markdown(f"<div class='driver-card'><b>{driver['driver']}</b><br><br><b>Why it matters:</b> {driver['why']}<br><br><b>How it affects valuation:</b> {driver['valuation_effect']}</div>", unsafe_allow_html=True)

st.header("DCF valuation")
forecast = dcf_results["projections"][["year", "revenue", "ebit", "unlevered_fcf", "pv_fcf"]].copy()
st.dataframe(forecast, use_container_width=True, hide_index=True)
st.write(f"Enterprise value: ${dcf_results['enterprise_value']:,.0f} million. Equity value: ${dcf_results['equity_value']:,.0f} million. Fair value per share: ${dcf_results['fair_value_per_share']:.2f}.")

st.header("Sensitivity analysis")
left, right = st.columns(2)
with left:
    st.subheader("WACC vs. terminal growth")
    st.dataframe(format_sensitivity(sensitivities["wacc_terminal_growth"]), use_container_width=True)
with right:
    st.subheader("Revenue growth vs. EBIT margin")
    st.dataframe(format_sensitivity(sensitivities["revenue_growth_ebit_margin"]), use_container_width=True)

st.header("How to read this dashboard")
st.markdown(
    """
- DCF fair value is not a stock-price prediction.
- Sensitivity analysis shows how assumption changes can move valuation.
- A stock appearing undervalued in one scenario does not mean it is a good investment.
- The goal is to understand what drives value, not to forecast the stock price perfectly.
"""
)

st.header("Investment memo")
render_memo(memo)

st.header("Project limitations and disclaimer")
st.markdown(
    """
<div class='warning-card'>
<ul>
<li>This is not investment advice.</li>
<li>DCF valuation is highly assumption-driven.</li>
<li>SEC XBRL tags can vary by company and year.</li>
<li>Sample fallback data is illustrative.</li>
<li>Auto-fetched market prices may be delayed or unavailable.</li>
</ul>
</div>
""",
    unsafe_allow_html=True,
)

st.header("Export")
st.write("Prepare an Excel workbook using the current data and assumptions.")
if st.button("Prepare Excel report", type="primary"):
    path = export_excel_report(
        ROOT / "outputs" / "EquityLens_NDAQ_MVP.xlsx",
        COMPANY,
        data,
        metrics,
        trends,
        assumptions,
        dcf_results,
        sensitivities,
        memo,
        metadata=data_result.metadata | {"price_source": price_source, "price_timestamp": price_timestamp},
        key_drivers=KEY_VALUE_DRIVERS,
    )
    st.session_state["excel_bytes"] = path.read_bytes()
if "excel_bytes" in st.session_state:
    st.download_button("Download Excel report", st.session_state["excel_bytes"], file_name="EquityLens_NDAQ.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
