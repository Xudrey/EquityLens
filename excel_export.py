"""Excel export for the focused MVP, inspired by a financial statement analysis workbook."""

from pathlib import Path
from typing import Any

import openpyxl
import pandas as pd

from .config import CompanyConfig, DCFAssumptions

REQUIRED_WORKBOOK_SHEETS = (
    "T1 - Cover",
    "T2 - Historical Financials",
    "T3 - Ratio Analysis",
    "T4 - DCF Forecast",
    "T5 - Sensitivity Analysis",
    "T6 - Key Value Drivers",
    "T7 - Investment Memo",
    "Data Source",
)

REQUIRED_WORKBOOK_ANCHORS = {
    "T1 - Cover": {"A1": "EQUITYLENS"},
    "T2 - Historical Financials": {
        "A1": "Historical Financials and Statement-Style Analysis",
        "A4": "Historical financials with vertical/horizontal-style ratios",
    },
    "T3 - Ratio Analysis": {"A1": "Ratio Analysis and Interpretation"},
    "T4 - DCF Forecast": {"A1": "DCF Forecast"},
    "T5 - Sensitivity Analysis": {"A1": "Sensitivity Analysis"},
    "T6 - Key Value Drivers": {
        "A1": "Key Value Drivers",
        "A4": "Nasdaq-specific value drivers",
    },
    "T7 - Investment Memo": {"A1": "Investment Memo"},
    "Data Source": {"A1": "Data Source and Workbook Notes"},
}

DEFAULT_VALUE_DRIVERS = [
    {
        "driver": "Recurring revenue growth",
        "why": "Recurring data, index, workflow, and technology revenue can support durability.",
        "valuation_effect": "Higher durable growth increases forecast cash flows.",
    },
    {
        "driver": "Operating margin stability",
        "why": "Margins show whether scale, integration, and competition are being managed well.",
        "valuation_effect": "Higher margins convert more revenue into EBIT and free cash flow.",
    },
    {
        "driver": "Free cash flow conversion",
        "why": "DCF value is driven by cash generation, not just accounting earnings.",
        "valuation_effect": "Better conversion increases discounted cash flows.",
    },
    {
        "driver": "Debt and acquisition integration risk",
        "why": "Leverage and integration costs can absorb cash and raise risk.",
        "valuation_effect": "More debt reduces equity value after enterprise value is calculated.",
    },
    {
        "driver": "WACC and terminal growth",
        "why": "Discount rate and terminal value are usually major DCF swing factors.",
        "valuation_effect": "Higher WACC lowers value; higher terminal growth raises value.",
    },
]


def _safe_sheet_name(name: str) -> str:
    """Keep sheet names inside Excel's 31-character limit."""
    return name[:31]


def validate_workbook_structure(path: str | Path) -> None:
    """Enforce the SWK-inspired financial statement analysis workbook structure."""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    sheet_names = tuple(workbook.sheetnames)
    if sheet_names != REQUIRED_WORKBOOK_SHEETS:
        raise ValueError(
            "Workbook structure does not match the required EquityLens export "
            f"flow. Expected {REQUIRED_WORKBOOK_SHEETS}, found {sheet_names}."
        )
    for sheet_name, cell_checks in REQUIRED_WORKBOOK_ANCHORS.items():
        worksheet = workbook[sheet_name]
        for cell, expected_value in cell_checks.items():
            actual_value = worksheet[cell].value
            if actual_value != expected_value:
                raise ValueError(
                    f"Workbook anchor mismatch on {sheet_name}!{cell}: "
                    f"expected {expected_value!r}, found {actual_value!r}."
                )


def _write_dataframe(
    worksheet,
    dataframe: pd.DataFrame,
    start_row: int,
    start_col: int,
    formats: dict[str, Any],
    *,
    title: str | None = None,
) -> int:
    """Write a DataFrame with consistent header and numeric formatting."""
    row = start_row
    if title:
        worksheet.merge_range(row, start_col, row, start_col + max(len(dataframe.columns) - 1, 1), title, formats["section"])
        row += 1
    worksheet.write_row(row, start_col, [str(c).replace("_", " ").title() for c in dataframe.columns], formats["header"])
    for r_idx, values in enumerate(dataframe.itertuples(index=False), start=row + 1):
        for c_idx, value in enumerate(values, start=start_col):
            column_name = str(dataframe.columns[c_idx - start_col])
            if pd.isna(value):
                worksheet.write_blank(r_idx, c_idx, None)
            elif isinstance(value, (int, float)):
                if "margin" in column_name or "growth" in column_name or "conversion" in column_name or "upside" in column_name or "cagr" in column_name or "pct" in column_name:
                    worksheet.write(r_idx, c_idx, float(value), formats["pct"])
                elif "share" in column_name or "price" in column_name or "fair_value" in column_name:
                    worksheet.write(r_idx, c_idx, float(value), formats["per_share"])
                elif column_name == "year":
                    worksheet.write(r_idx, c_idx, int(value), formats["integer"])
                else:
                    worksheet.write(r_idx, c_idx, float(value), formats["money"])
            else:
                worksheet.write(r_idx, c_idx, value, formats["text"])
    return row + len(dataframe) + 2


def _make_formats(workbook) -> dict[str, Any]:
    navy, teal, cream, ink = "#14213D", "#168F82", "#F4F1EA", "#202733"
    return {
        "title": workbook.add_format({"bold": True, "font_size": 18, "font_color": "#FFFFFF", "bg_color": navy, "align": "center", "valign": "vcenter"}),
        "subtitle": workbook.add_format({"font_size": 11, "font_color": ink, "italic": True, "align": "center"}),
        "section": workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": teal, "align": "left"}),
        "header": workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": navy, "align": "center", "border": 1}),
        "label": workbook.add_format({"bold": True, "font_color": ink, "bg_color": cream}),
        "text": workbook.add_format({"font_color": ink, "text_wrap": True, "valign": "top"}),
        "money": workbook.add_format({"num_format": '$#,##0;[Red]($#,##0);-', "font_color": ink}),
        "per_share": workbook.add_format({"num_format": '$0.00;[Red]($0.00);-', "font_color": ink}),
        "pct": workbook.add_format({"num_format": '0.0%;[Red](0.0%);-', "font_color": ink}),
        "integer": workbook.add_format({"num_format": '#,##0', "font_color": ink}),
        "input": workbook.add_format({"num_format": '0.0%', "font_color": "#0000FF", "bg_color": "#FFF4B8"}),
        "note": workbook.add_format({"font_color": "#667085", "italic": True, "text_wrap": True}),
    }


def export_excel_report(
    output_path: str | Path,
    company: CompanyConfig,
    raw_data: pd.DataFrame,
    ratios: pd.DataFrame,
    trends: dict[str, Any],
    assumptions: DCFAssumptions,
    dcf_results: dict[str, Any],
    sensitivities: dict[str, pd.DataFrame],
    memo: str,
    *,
    metadata: dict[str, Any],
    key_drivers: list[dict[str, str]] | None = None,
) -> Path:
    """Write an auditable workbook patterned after a financial statement analysis project."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    drivers = key_drivers or DEFAULT_VALUE_DRIVERS

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        workbook = writer.book
        formats = _make_formats(workbook)
        sheets = {
            name: workbook.add_worksheet(_safe_sheet_name(name))
            for name in REQUIRED_WORKBOOK_SHEETS
        }
        writer.sheets.update(sheets)
        for sheet in sheets.values():
            sheet.hide_gridlines(2)
            sheet.set_tab_color("#168F82")

        cover = sheets["T1 - Cover"]
        cover.merge_range("A1:H1", "EQUITYLENS", formats["title"])
        cover.merge_range("A3:H3", "AI-assisted financial analysis and valuation dashboard", formats["subtitle"])
        cover.write("A5", "Company", formats["label"]); cover.write("B5", company.company_name, formats["text"])
        cover.write("A6", "Ticker", formats["label"]); cover.write("B6", company.ticker, formats["text"])
        cover.write("A7", "Source", formats["label"]); cover.write("B7", metadata.get("source", "Not available"), formats["text"])
        cover.write("A8", "Current Price", formats["label"]); cover.write("B8", dcf_results["current_share_price"], formats["per_share"])
        cover.write("A9", "DCF Fair Value", formats["label"]); cover.write("B9", dcf_results["fair_value_per_share"], formats["per_share"])
        cover.write("A10", "Implied Upside / Downside", formats["label"]); cover.write("B10", dcf_results["upside_downside"], formats["pct"])
        cover.merge_range("A12:H15", "Purpose: convert public company financial data into a structured valuation view. This workbook follows a financial-statement-analysis flow: historical financials, ratio analysis, DCF forecast, sensitivity analysis, value drivers, and memo-style interpretation. Educational use only; not investment advice.", formats["text"])
        cover.set_column("A:A", 24); cover.set_column("B:H", 18)

        historical = sheets["T2 - Historical Financials"]
        historical.merge_range("A1:K1", "Historical Financials and Statement-Style Analysis", formats["title"])
        history = raw_data.copy()
        history["revenue_yoy_growth"] = history["revenue"].pct_change()
        history["ebit_margin"] = history["ebit"] / history["revenue"]
        history["fcf_margin"] = history["free_cash_flow"] / history["revenue"]
        history["debt_to_revenue"] = history["total_debt"] / history["revenue"]
        _write_dataframe(historical, history, 3, 0, formats, title="Historical financials with vertical/horizontal-style ratios")
        historical.freeze_panes(5, 1)
        historical.set_column("A:A", 11); historical.set_column("B:K", 16)

        ratio = sheets["T3 - Ratio Analysis"]
        ratio.merge_range("A1:H1", "Ratio Analysis and Interpretation", formats["title"])
        ratio_cols = ["year", "revenue_growth", "ebit_margin", "net_margin", "fcf_margin", "fcf_conversion", "debt_to_fcf"]
        _write_dataframe(ratio, ratios[ratio_cols], 3, 0, formats, title="Core ratios")
        row = len(ratios) + 8
        ratio.write(row, 0, "Interpretation", formats["section"])
        interpretations = [
            ("Revenue trend", f"Revenue has {trends['revenue_trend']} over the selected period. Revenue CAGR is {trends['revenue_cagr']:.1%}."),
            ("Margin trend", f"EBIT margin has {trends['margin_trend']}; latest EBIT margin is {trends['latest_ebit_margin']:.1%}."),
            ("Cash generation", f"Free cash flow was {trends['fcf_trend']}; latest FCF margin is {trends['latest_fcf_margin']:.1%}."),
            ("Leverage", f"Latest debt / FCF is {trends['latest_debt_to_fcf']:.1f}x."),
        ]
        for i, (label, text) in enumerate(interpretations, start=row + 1):
            ratio.write(i, 0, label, formats["label"])
            ratio.merge_range(i, 1, i, 7, text, formats["text"])
        ratio.set_column("A:A", 18); ratio.set_column("B:H", 18)

        forecast = sheets["T4 - DCF Forecast"]
        forecast.merge_range("A1:H1", "DCF Forecast", formats["title"])
        assumption_rows = pd.DataFrame([
            {"assumption": "Revenue growth", "value": assumptions.revenue_growth},
            {"assumption": "EBIT margin", "value": assumptions.ebit_margin},
            {"assumption": "Tax rate", "value": assumptions.tax_rate},
            {"assumption": "D&A / revenue", "value": assumptions.da_pct_revenue},
            {"assumption": "Capex / revenue", "value": assumptions.capex_pct_revenue},
            {"assumption": "NWC / incremental revenue", "value": assumptions.nwc_pct_revenue},
            {"assumption": "WACC", "value": assumptions.wacc},
            {"assumption": "Terminal growth", "value": assumptions.terminal_growth},
        ])
        _write_dataframe(forecast, assumption_rows, 3, 0, formats, title="Base assumptions")
        _write_dataframe(forecast, dcf_results["projections"], 15, 0, formats, title="Forecast projection")
        bridge = pd.DataFrame([
            {"metric": "PV of forecast FCF", "value": dcf_results["pv_forecast_fcf"]},
            {"metric": "PV of terminal value", "value": dcf_results["pv_terminal_value"]},
            {"metric": "Enterprise value", "value": dcf_results["enterprise_value"]},
            {"metric": "Cash", "value": dcf_results["cash"]},
            {"metric": "Debt", "value": dcf_results["debt"]},
            {"metric": "Equity value", "value": dcf_results["equity_value"]},
            {"metric": "Diluted shares", "value": dcf_results["diluted_shares"]},
            {"metric": "Fair value / share", "value": dcf_results["fair_value_per_share"]},
            {"metric": "Current share price", "value": dcf_results["current_share_price"]},
            {"metric": "Upside / downside", "value": dcf_results["upside_downside"]},
        ])
        _write_dataframe(forecast, bridge, 29, 0, formats, title="Valuation bridge")
        forecast.set_column("A:A", 26); forecast.set_column("B:H", 17)

        sens = sheets["T5 - Sensitivity Analysis"]
        sens.merge_range("A1:K1", "Sensitivity Analysis", formats["title"])
        wacc_table = sensitivities["wacc_terminal_growth"].reset_index()
        op_table = sensitivities["revenue_growth_ebit_margin"].reset_index()
        _write_dataframe(sens, wacc_table, 3, 0, formats, title="WACC vs. terminal growth")
        _write_dataframe(sens, op_table, 13, 0, formats, title="Revenue growth vs. EBIT margin")
        sens.set_column("A:K", 16)

        driver_sheet = sheets["T6 - Key Value Drivers"]
        driver_sheet.merge_range("A1:C1", "Key Value Drivers", formats["title"])
        driver_df = pd.DataFrame(drivers)
        _write_dataframe(driver_sheet, driver_df, 3, 0, formats, title="Nasdaq-specific value drivers")
        driver_sheet.set_column("A:A", 28); driver_sheet.set_column("B:C", 65)

        memo_sheet = sheets["T7 - Investment Memo"]
        memo_sheet.merge_range("A1:H1", "Investment Memo", formats["title"])
        row = 3
        for block in memo.split("\n\n"):
            heading, body = block.split("\n", 1)
            memo_sheet.merge_range(row, 0, row, 7, heading, formats["section"])
            memo_sheet.merge_range(row + 1, 0, row + 3, 7, body, formats["text"])
            row += 5
        memo_sheet.set_column("A:H", 17)

        source = sheets["Data Source"]
        source.merge_range("A1:D1", "Data Source and Workbook Notes", formats["title"])
        metadata_df = pd.DataFrame([metadata])
        _write_dataframe(source, metadata_df, 3, 0, formats, title="Source metadata")
        source.merge_range("A9:D12", "Workbook structure is inspired by the provided financial statement analysis sample: cover page, historical financials, ratio analysis, forecast, sensitivity, value drivers, and memo. SWK workbook data was used only as a layout/workflow reference, not as a source for Nasdaq valuation inputs.", formats["note"])
        source.set_column("A:D", 30)

        workbook.set_properties({"title": "EquityLens NDAQ MVP", "subject": "Financial analysis and valuation workbook", "author": "EquityLens"})
    validate_workbook_structure(output)
    return output
