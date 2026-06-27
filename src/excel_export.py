"""Create the polished EquityLens Excel report using XlsxWriter."""

from pathlib import Path
from typing import Any

import pandas as pd

from .config import CompanyConfig, DCFAssumptions


def export_excel_report(
    output_path: str | Path,
    company: CompanyConfig,
    raw_data: pd.DataFrame,
    ratios: pd.DataFrame,
    trend_summary: dict[str, Any],
    assumptions: DCFAssumptions,
    dcf_results: dict[str, Any],
    sensitivities: dict[str, pd.DataFrame],
    memo: str,
    *,
    source_data: pd.DataFrame,
    tags_used: pd.DataFrame,
    quality_notes: pd.DataFrame,
    metadata: dict[str, Any],
    monte_carlo: dict[str, Any] | None = None,
) -> Path:
    """Write an analyst-style, formula-driven Excel workbook."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        workbook = writer.book
        is_sample_fallback = bool(metadata.get("is_sample_fallback"))
        navy, teal, cream, ink = "#14213D", "#18A999", "#F4F1EA", "#202733"
        light_teal, light_blue = "#DDF4EF", "#E9F0FA"
        title = workbook.add_format({"bold": True, "font_size": 22, "font_color": "#FFFFFF", "bg_color": navy, "align": "left", "valign": "vcenter"})
        subtitle = workbook.add_format({"font_size": 10, "font_color": "#D9E4F2", "bg_color": navy})
        section = workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": navy, "align": "left", "bottom": 1, "bottom_color": teal})
        label = workbook.add_format({"bold": True, "font_color": ink, "bg_color": cream, "border": 0})
        value = workbook.add_format({"font_size": 14, "bold": True, "font_color": navy, "bg_color": "#FFFFFF", "bottom": 2, "bottom_color": teal})
        money = workbook.add_format({"num_format": '$#,##0;[Red]($#,##0);-', "font_color": ink})
        per_share = workbook.add_format({"num_format": '$0.00;[Red]($0.00);-', "font_color": ink})
        pct = workbook.add_format({"num_format": '0.0%;[Red](0.0%);-', "font_color": ink})
        multiple = workbook.add_format({"num_format": '0.0x;[Red](0.0x);-', "font_color": ink})
        integer = workbook.add_format({"num_format": '#,##0;[Red](#,##0);-', "font_color": ink})
        input_pct = workbook.add_format({"num_format": '0.0%', "font_color": "#0000FF", "bg_color": "#FFF4B8"})
        formula_money = workbook.add_format({"num_format": '$#,##0;[Red]($#,##0);-', "font_color": "#000000"})
        formula_per_share = workbook.add_format({"num_format": '$0.00;[Red]($0.00);-', "font_color": "#000000"})
        linked_money = workbook.add_format({"num_format": '$#,##0;[Red]($#,##0);-', "font_color": "#008000"})
        linked_pct = workbook.add_format({"num_format": '0.0%', "font_color": "#008000"})
        note = workbook.add_format({"font_color": "#5D6776", "italic": True, "font_size": 9, "text_wrap": True})
        memo_fmt = workbook.add_format({"font_color": ink, "text_wrap": True, "valign": "top", "bg_color": "#FFFFFF"})
        table_header = workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": navy, "bottom": 2, "bottom_color": teal, "align": "center"})

        # Create every required tab before adding cross-sheet formulas.
        sheet_names = [
            "Dashboard",
            "Source Data",
            "Raw Financials",
            "Ratio Analysis",
            "DCF Model",
            "Sensitivity Analysis",
            "Monte Carlo Summary",
            "Monte Carlo Results",
            "Monte Carlo Sensitivity",
            "Monte Carlo Drivers",
            "Monte Carlo Explanation",
            "Investment Memo Draft",
            "SEC Tags Used",
            "Data Quality Notes",
            "Checks",
        ]
        sheets = {name: workbook.add_worksheet(name) for name in sheet_names}
        writer.sheets.update(sheets)
        for sheet in sheets.values():
            sheet.hide_gridlines(2)
            sheet.set_tab_color(teal)

        raw = sheets["Raw Financials"]
        raw_title = "Raw Financials | SAMPLE FALLBACK" if is_sample_fallback else "Raw Financials | SEC 10-K DATA"
        raw.merge_range(0, 0, 0, len(raw_data.columns) - 1, raw_title, title)
        raw.merge_range(1, 0, 1, len(raw_data.columns) - 1, "USD and shares in millions except per-share data. Market-price source is shown on the Dashboard.", subtitle)
        raw.write_row(3, 0, [c.replace("_", " ").title() for c in raw_data.columns], table_header)
        for r, row in enumerate(raw_data.itertuples(index=False), start=4):
            for c, val in enumerate(row):
                if c == 0:
                    fmt = integer
                elif raw_data.columns[c] in {"current_share_price", "diluted_eps"}:
                    fmt = per_share
                elif raw_data.columns[c] == "source":
                    fmt = note
                else:
                    fmt = money
                raw.write_blank(r, c, None, fmt) if pd.isna(val) else raw.write(r, c, val, fmt)
        raw.add_table(3, 0, 3 + len(raw_data), len(raw_data.columns) - 1, {"name": "RawFinancialsTable", "columns": [{"header": c.replace("_", " ").title()} for c in raw_data.columns], "style": "Table Style Medium 2"})
        raw.freeze_panes(4, 1)
        raw.set_column("A:A", 10)
        raw.set_column(1, min(11, len(raw_data.columns) - 1), 18)
        if "source" in raw_data.columns:
            raw.set_column(raw_data.columns.get_loc("source"), raw_data.columns.get_loc("source"), 70)

        source_sheet = sheets["Source Data"]
        source_title = "Sample Fallback Source Data" if is_sample_fallback else "Selected SEC Company Facts"
        source_sheet.merge_range(0, 0, 0, max(0, len(source_data.columns) - 1), source_title, title)
        source_sheet.merge_range(1, 0, 1, max(0, len(source_data.columns) - 1), metadata.get("api_url", "SEC EDGAR companyfacts API"), subtitle)
        if not source_data.empty:
            source_sheet.write_row(3, 0, [c.replace("_", " ").title() for c in source_data.columns], table_header)
            for r, row in enumerate(source_data.itertuples(index=False), start=4):
                for c, val in enumerate(row):
                    fmt = money if source_data.columns[c] == "value" else None
                    source_sheet.write_blank(r, c, None, fmt) if pd.isna(val) else source_sheet.write(r, c, val, fmt)
            source_sheet.add_table(3, 0, 3 + len(source_data), len(source_data.columns) - 1, {"name": "SECSourceDataTable", "columns": [{"header": c.replace("_", " ").title()} for c in source_data.columns], "style": "Table Style Medium 2"})
        source_sheet.freeze_panes(4, 2)
        source_sheet.set_column(0, 2, 17)
        source_sheet.set_column(3, max(3, len(source_data.columns) - 1), 24)

        ratio = sheets["Ratio Analysis"]
        ratio.merge_range("A1:G1", "Historical Ratio Analysis", title)
        ratio_subtitle = "Margins, conversion, leverage, and growth derived from illustrative sample data." if is_sample_fallback else "Margins, conversion, leverage, and growth derived from annual SEC 10-K facts."
        ratio.merge_range("A2:G2", ratio_subtitle, subtitle)
        ratio_headers = ["Year", "Revenue Growth", "EBIT Margin", "Net Margin", "FCF Margin", "FCF Conversion", "Debt / FCF"]
        ratio.write_row("A4", ratio_headers, table_header)
        ratio_cols = ["year", "revenue_growth", "ebit_margin", "net_margin", "fcf_margin", "fcf_conversion", "debt_to_fcf"]
        for r, row in enumerate(ratios[ratio_cols].itertuples(index=False), start=4):
            ratio.write(r, 0, row[0], integer)
            for c in range(1, 6):
                ratio.write_blank(r, c, None, pct) if pd.isna(row[c]) else ratio.write(r, c, row[c], pct)
            ratio.write(r, 6, row[6], multiple)
        ratio.write("I4", "Trend Summary", section)
        summaries = [
            ("Revenue CAGR", trend_summary["revenue_cagr"], pct),
            ("Latest EBIT Margin", trend_summary["latest_ebit_margin"], pct),
            ("Latest FCF Margin", trend_summary["latest_fcf_margin"], pct),
            ("Latest Debt / FCF", trend_summary["latest_debt_to_fcf"], multiple),
        ]
        for i, (name, val, fmt) in enumerate(summaries, start=5):
            ratio.write(i, 8, name, label)
            ratio.write(i, 9, val, fmt)
        ratio.freeze_panes(4, 1)
        ratio.set_column("A:A", 10)
        ratio.set_column("B:G", 17)
        ratio.set_column("I:I", 22)
        ratio.set_column("J:J", 16)

        dcf = sheets["DCF Model"]
        dcf.merge_range("A1:G1", "Discounted Cash Flow Model", title)
        dcf.merge_range("A2:G2", "Five-year unlevered FCF model | Gordon Growth terminal value | USD millions except per share", subtitle)
        dcf.merge_range("A4:B4", "Editable Assumptions", section)
        assumption_rows = [
            ("Revenue Growth", assumptions.revenue_growth), ("EBIT Margin", assumptions.ebit_margin),
            ("Tax Rate", assumptions.tax_rate), ("D&A / Revenue", assumptions.da_pct_revenue),
            ("Capex / Revenue", assumptions.capex_pct_revenue), ("NWC / Incremental Revenue", assumptions.nwc_pct_revenue),
            ("WACC", assumptions.wacc), ("Terminal Growth", assumptions.terminal_growth),
        ]
        for row, (name, val) in enumerate(assumption_rows, start=4):
            dcf.write(row, 0, name, label)
            dcf.write(row, 1, val, input_pct)
        dcf.write("A14", "Blue font / yellow fill = editable assumption", note)
        dcf.merge_range("A16:G16", "Projection", section)
        years = dcf_results["projections"]["year"].tolist()
        dcf.write_row("A17", ["Metric"] + years, table_header)
        base_row = 17
        latest_revenue = len(raw_data) + 3
        projection_rows = ["Revenue", "EBIT", "Taxes", "NOPAT", "D&A", "Capex", "Change in NWC", "Unlevered FCF", "Discount Factor", "PV of FCF"]
        for i, name in enumerate(projection_rows, start=base_row):
            dcf.write(i, 0, name, label if name not in {"Unlevered FCF", "PV of FCF"} else section)
        for col in range(1, 6):
            letter = chr(65 + col)
            prev_rev = f"'Raw Financials'!B{latest_revenue+1}" if col == 1 else f"{chr(65+col)}18"
            formulas = [
                f"={prev_rev}*(1+$B$5)", f"={letter}18*$B$6", f"={letter}19*$B$7", f"={letter}19-{letter}20",
                f"={letter}18*$B$8", f"={letter}18*$B$9", f"=({letter}18-{prev_rev})*$B$10",
                f"={letter}21+{letter}22-{letter}23-{letter}24", f"=1/(1+$B$11)^{col}", f"={letter}25*{letter}26",
            ]
            for row_offset, formula in enumerate(formulas):
                fmt = linked_money if (col == 1 and row_offset == 0) else (linked_pct if row_offset == 8 else formula_money)
                dcf.write_formula(base_row + row_offset, col, formula, fmt)
        dcf.merge_range("A29:B29", "Valuation Bridge", section)
        bridge = [
            ("PV of Forecast FCF", "=SUM(B27:F27)", formula_money),
            ("Terminal Value", "=F25*(1+$B$12)/($B$11-$B$12)", formula_money),
            ("PV of Terminal Value", "=B31*F26", formula_money),
            ("Enterprise Value", "=B30+B32", formula_money),
            ("Cash", f"='Raw Financials'!H{latest_revenue+1}", linked_money),
            ("Debt", f"='Raw Financials'!I{latest_revenue+1}", linked_money),
            ("Equity Value", "=B33+B34-B35", formula_money),
            ("Diluted Shares", f"='Raw Financials'!J{latest_revenue+1}", linked_money),
            ("Fair Value / Share", "=B36/B37", formula_per_share),
            ("Current Share Price", f"='Raw Financials'!K{latest_revenue+1}", formula_per_share),
            ("Upside / (Downside)", "=B38/B39-1", pct),
        ]
        for row, (name, formula, fmt) in enumerate(bridge, start=29):
            dcf.write(row, 0, name, label)
            dcf.write_formula(row, 1, formula, fmt)
        dcf.set_column("A:A", 28)
        dcf.set_column("B:F", 15)
        dcf.freeze_panes(17, 1)

        sens = sheets["Sensitivity Analysis"]
        sens.merge_range("A1:G1", "Sensitivity Analysis", title)
        sens.merge_range("A2:G2", "Fair value per share under alternative valuation and operating assumptions.", subtitle)
        for start_row, name, table in [(3, "WACC vs. Terminal Growth", sensitivities["wacc_terminal_growth"]), (13, "Revenue Growth vs. EBIT Margin", sensitivities["revenue_growth_ebit_margin"])]:
            sens.merge_range(start_row, 0, start_row, 5, name, section)
            sens.write(start_row + 1, 0, table.index.name, table_header)
            for c, val in enumerate(table.columns, start=1):
                sens.write(start_row + 1, c, val, table_header)
            for r, (idx, values_) in enumerate(table.iterrows(), start=start_row + 2):
                sens.write(r, 0, idx, pct)
                for c, val in enumerate(values_, start=1):
                    sens.write(r, c, val, per_share)
            sens.conditional_format(start_row + 2, 1, start_row + 6, 5, {"type": "3_color_scale", "min_color": "#F7C6C7", "mid_color": "#FFF4B8", "max_color": "#BFE5D8"})
        sens.set_column("A:A", 22)
        sens.set_column("B:F", 15)

        mc_summary_sheet = sheets["Monte Carlo Summary"]
        mc_results_sheet = sheets["Monte Carlo Results"]
        mc_sensitivity_sheet = sheets["Monte Carlo Sensitivity"]
        mc_drivers_sheet = sheets["Monte Carlo Drivers"]
        mc_explanation_sheet = sheets["Monte Carlo Explanation"]
        if monte_carlo:
            mc_summary_sheet.merge_range("A1:E1", "Monte Carlo Valuation Summary", title)
            mc_summary_sheet.merge_range("A2:E2", "Python-native pandas/numpy simulation. No Argo or paid API dependency.", subtitle)
            summary = monte_carlo["summary"]
            summary_rows = [
                ("Simulations Run", summary["simulations_run"], integer),
                ("Valid Simulations", summary["valid_simulations"], integer),
                ("Current Price", summary["current_price"], per_share),
                ("Mean Fair Value", summary["mean_fair_value"], per_share),
                ("Median Fair Value", summary["median_fair_value"], per_share),
                ("5th Percentile", summary["percentile_5"], per_share),
                ("10th Percentile", summary["percentile_10"], per_share),
                ("25th Percentile", summary["percentile_25"], per_share),
                ("75th Percentile", summary["percentile_75"], per_share),
                ("90th Percentile", summary["percentile_90"], per_share),
                ("95th Percentile", summary["percentile_95"], per_share),
                ("Probability Above Current Price", summary["probability_above_current_price"], pct),
                ("Median Implied Upside / Downside", summary["median_implied_upside_downside"], pct),
                ("Base Case Fair Value", summary.get("base_case_fair_value"), per_share),
                ("Valuation Label", summary["valuation_label"], value),
                ("Confidence Note", summary["confidence_note"], memo_fmt),
            ]
            mc_summary_sheet.write_row("A4", ["Metric", "Value"], table_header)
            for r, (name, val, fmt) in enumerate(summary_rows, start=4):
                mc_summary_sheet.write(r, 0, name, label)
                if val is None or pd.isna(val):
                    mc_summary_sheet.write_blank(r, 1, None, fmt)
                else:
                    mc_summary_sheet.write(r, 1, val, fmt)

            percentile_data = monte_carlo.get("percentiles", pd.DataFrame())
            if not percentile_data.empty:
                start_row = 23
                mc_summary_sheet.write_row(start_row, 0, ["Percentile", "Fair Value / Share"], table_header)
                for r, row in enumerate(percentile_data.itertuples(index=False), start=start_row + 1):
                    mc_summary_sheet.write(r, 0, row.percentile)
                    mc_summary_sheet.write(r, 1, row.fair_value_per_share, per_share)
                percentile_chart = workbook.add_chart({"type": "column"})
                percentile_chart.add_series(
                    {
                        "name": "Fair Value / Share",
                        "categories": f"='Monte Carlo Summary'!$A${start_row + 2}:$A${start_row + 1 + len(percentile_data)}",
                        "values": f"='Monte Carlo Summary'!$B${start_row + 2}:$B${start_row + 1 + len(percentile_data)}",
                        "fill": {"color": navy},
                    }
                )
                percentile_chart.set_title({"name": "Fair Value Percentiles"})
                percentile_chart.set_y_axis({"num_format": "$0.00"})
                percentile_chart.set_chartarea({"border": {"none": True}})
                mc_summary_sheet.insert_chart("D4", percentile_chart, {"x_scale": 1.1, "y_scale": 1.0})

            histogram = monte_carlo.get("histogram", pd.DataFrame())
            if not histogram.empty:
                histogram_start = 34
                headers = [c.replace("_", " ").title() for c in histogram.columns]
                mc_summary_sheet.write_row(histogram_start, 0, headers, table_header)
                for r, row in enumerate(histogram.itertuples(index=False), start=histogram_start + 1):
                    for c, val in enumerate(row):
                        mc_summary_sheet.write(r, c, val, money if c < 3 else integer)

            simulation_df = monte_carlo["simulation_df"]
            mc_results_sheet.merge_range(0, 0, 0, len(simulation_df.columns) - 1, "Monte Carlo Simulation Results", title)
            mc_results_sheet.merge_range(1, 0, 1, len(simulation_df.columns) - 1, "One row per simulation; assumption draws and valuation outputs.", subtitle)
            mc_results_sheet.write_row(3, 0, [c.replace("_", " ").title() for c in simulation_df.columns], table_header)
            for r, row in enumerate(simulation_df.itertuples(index=False), start=4):
                for c, val in enumerate(row):
                    if pd.isna(val):
                        mc_results_sheet.write_blank(r, c, None)
                    elif simulation_df.columns[c] in {
                        "revenue_growth",
                        "ebit_margin",
                        "tax_rate",
                        "fcf_margin",
                        "fcf_conversion",
                        "wacc",
                        "terminal_growth",
                        "implied_upside_downside",
                    }:
                        mc_results_sheet.write(r, c, val, pct)
                    elif simulation_df.columns[c] == "simulation_id":
                        mc_results_sheet.write(r, c, val, integer)
                    elif simulation_df.columns[c] == "valid_simulation":
                        mc_results_sheet.write(r, c, "TRUE" if val else "FALSE")
                    elif simulation_df.columns[c] == "fair_value_per_share":
                        mc_results_sheet.write(r, c, val, per_share)
                    else:
                        mc_results_sheet.write(r, c, val, money)
            mc_results_sheet.freeze_panes(4, 1)
            mc_results_sheet.set_column(0, len(simulation_df.columns) - 1, 18)

            mc_sensitivity = monte_carlo["sensitivity"]
            mc_sensitivity_sheet.merge_range(0, 0, 0, max(2, len(mc_sensitivity.columns) - 1), "Monte Carlo Assumption Sensitivity", title)
            mc_sensitivity_sheet.merge_range(1, 0, 1, max(2, len(mc_sensitivity.columns) - 1), "Pearson correlation between assumption draws and fair value per share.", subtitle)
            if not mc_sensitivity.empty:
                mc_sensitivity_sheet.write_row(3, 0, [c.replace("_", " ").title() for c in mc_sensitivity.columns], table_header)
                for r, row in enumerate(mc_sensitivity.itertuples(index=False), start=4):
                    for c, val in enumerate(row):
                        if pd.isna(val):
                            mc_sensitivity_sheet.write_blank(r, c, None)
                        elif c == 0:
                            mc_sensitivity_sheet.write(r, c, val)
                        else:
                            mc_sensitivity_sheet.write(r, c, val, workbook.add_format({"num_format": "0.00", "font_color": ink}))
                mc_sensitivity_sheet.conditional_format(
                    4,
                    1,
                    3 + len(mc_sensitivity),
                    1,
                    {"type": "3_color_scale", "min_color": "#F7C6C7", "mid_color": "#FFF4B8", "max_color": "#BFE5D8"},
                )
            mc_summary_sheet.set_column("A:A", 28)
            mc_summary_sheet.set_column("B:E", 18)
            mc_sensitivity_sheet.set_column(0, max(2, len(mc_sensitivity.columns) - 1), 24)

            value_driver_table = monte_carlo.get("value_driver_table", pd.DataFrame())
            mc_drivers_sheet.merge_range(0, 0, 0, max(4, len(value_driver_table.columns) - 1), "Monte Carlo Value Drivers", title)
            mc_drivers_sheet.merge_range(1, 0, 1, max(4, len(value_driver_table.columns) - 1), "Driver ranking, distribution choices, and simulation constraints.", subtitle)
            if not value_driver_table.empty:
                mc_drivers_sheet.write_row(3, 0, [c.replace("_", " ").title() for c in value_driver_table.columns], table_header)
                for r, row in enumerate(value_driver_table.itertuples(index=False), start=4):
                    for c, val in enumerate(row):
                        if pd.isna(val):
                            mc_drivers_sheet.write_blank(r, c, None)
                        elif isinstance(val, (int, float)):
                            mc_drivers_sheet.write(r, c, val, pct if "score" in value_driver_table.columns[c] else None)
                        else:
                            mc_drivers_sheet.write(r, c, val, memo_fmt)
                mc_drivers_sheet.add_table(
                    3,
                    0,
                    3 + len(value_driver_table),
                    len(value_driver_table.columns) - 1,
                    {
                        "name": "MonteCarloDriversTable",
                        "columns": [{"header": c.replace("_", " ").title()} for c in value_driver_table.columns],
                        "style": "Table Style Medium 2",
                    },
                )
            mc_drivers_sheet.freeze_panes(4, 1)
            mc_drivers_sheet.set_column(0, 0, 22)
            mc_drivers_sheet.set_column(1, max(1, len(value_driver_table.columns) - 1), 28)

            explanation_text = monte_carlo.get("explanation", "")
            mc_explanation_sheet.merge_range("A1:H1", "Monte Carlo Explanation", title)
            mc_explanation_sheet.merge_range("A2:H2", "Plain-English explanation of the simulation workflow, distributions, constraints, and valuation label.", subtitle)
            mc_explanation_sheet.merge_range("A4:H10", explanation_text, memo_fmt)
            mc_explanation_sheet.set_column("A:H", 18)
        else:
            for sheet, sheet_title in [
                (mc_summary_sheet, "Monte Carlo Valuation Summary"),
                (mc_results_sheet, "Monte Carlo Simulation Results"),
                (mc_sensitivity_sheet, "Monte Carlo Assumption Sensitivity"),
                (mc_drivers_sheet, "Monte Carlo Value Drivers"),
                (mc_explanation_sheet, "Monte Carlo Explanation"),
            ]:
                sheet.merge_range("A1:D1", sheet_title, title)
                sheet.merge_range(
                    "A2:D2",
                    "Monte Carlo simulation was not run for this export.",
                    subtitle,
                )

        memo_sheet = sheets["Investment Memo Draft"]
        memo_sheet.merge_range("A1:H1", "Investment Memo Draft", title)
        memo_subtitle = "Rule-based first draft | No paid API used | SAMPLE DATA FALLBACK" if is_sample_fallback else "Rule-based first draft | No paid API used | SEC filing-grounded financials"
        memo_sheet.merge_range("A2:H2", memo_subtitle, subtitle)
        row = 4
        for block in memo.split("\n\n"):
            heading, body = block.split("\n", 1)
            memo_sheet.merge_range(row, 0, row, 7, heading, section)
            memo_sheet.merge_range(row + 1, 0, row + 3, 7, body, memo_fmt)
            memo_sheet.set_row(row + 1, 28)
            memo_sheet.set_row(row + 2, 28)
            memo_sheet.set_row(row + 3, 28)
            row += 5
        memo_sheet.set_column("A:H", 16)

        tags_sheet = sheets["SEC Tags Used"]
        tags_sheet.merge_range(0, 0, 0, max(0, len(tags_used.columns) - 1), "SEC XBRL Tags Used", title)
        tags_sheet.merge_range(1, 0, 1, max(0, len(tags_used.columns) - 1), "Fallback rank 1 is preferred. Review proxy and component methods before relying on the valuation.", subtitle)
        if not tags_used.empty:
            tags_sheet.write_row(3, 0, [c.replace("_", " ").title() for c in tags_used.columns], table_header)
            for r, row in enumerate(tags_used.itertuples(index=False), start=4):
                for c, val in enumerate(row):
                    tags_sheet.write_blank(r, c, None) if pd.isna(val) else tags_sheet.write(r, c, val)
            tags_sheet.add_table(3, 0, 3 + len(tags_used), len(tags_used.columns) - 1, {"name": "SECTagsUsedTable", "columns": [{"header": c.replace("_", " ").title()} for c in tags_used.columns], "style": "Table Style Medium 2"})
        tags_sheet.freeze_panes(4, 0)
        tags_sheet.set_column(0, max(0, len(tags_used.columns) - 1), 22)

        quality_sheet = sheets["Data Quality Notes"]
        quality_sheet.merge_range(0, 0, 0, max(3, len(quality_notes.columns) - 1), "Data Quality Notes", title)
        quality_sheet.merge_range(1, 0, 1, max(3, len(quality_notes.columns) - 1), "Warnings identify missing concepts, proxies, restricted cash, partial debt, and calculated fields.", subtitle)
        if not quality_notes.empty:
            quality_sheet.write_row(3, 0, [c.replace("_", " ").title() for c in quality_notes.columns], table_header)
            for r, row in enumerate(quality_notes.itertuples(index=False), start=4):
                for c, val in enumerate(row):
                    quality_sheet.write_blank(r, c, None) if pd.isna(val) else quality_sheet.write(r, c, val, note if quality_notes.columns[c] == "note" else None)
            quality_sheet.add_table(3, 0, 3 + len(quality_notes), len(quality_notes.columns) - 1, {"name": "DataQualityNotesTable", "columns": [{"header": c.replace("_", " ").title()} for c in quality_notes.columns], "style": "Table Style Medium 2"})
        quality_sheet.freeze_panes(4, 0)
        quality_sheet.set_column("A:C", 18)
        quality_sheet.set_column("D:D", 85)

        checks = sheets["Checks"]
        checks.merge_range("A1:F1", "Model Checks", title)
        checks.write_row("A3", ["Check", "Actual", "Expected", "Difference", "Tolerance", "Status"], table_header)
        check_rows = [
            ("FCF component tie", "='DCF Model'!B25", "='DCF Model'!B21+'DCF Model'!B22-'DCF Model'!B23-'DCF Model'!B24", 0.01),
            ("EV valuation bridge", "='DCF Model'!B33", "='DCF Model'!B30+'DCF Model'!B32", 0.01),
            ("Equity bridge", "='DCF Model'!B36", "='DCF Model'!B33+'DCF Model'!B34-'DCF Model'!B35", 0.01),
            ("WACC above terminal growth", "='DCF Model'!B11", "='DCF Model'!B12", 0),
        ]
        for r, (name, actual, expected, tolerance) in enumerate(check_rows, start=3):
            checks.write(r, 0, name)
            checks.write_formula(r, 1, actual)
            checks.write_formula(r, 2, expected)
            if name == "WACC above terminal growth":
                checks.write_formula(r, 3, "=B7-C7", pct)
                checks.write(r, 4, tolerance, pct)
                checks.write_formula(r, 5, '=IF(D7>0,"OK","FAIL")')
            else:
                checks.write_formula(r, 3, f"=B{r+1}-C{r+1}", formula_money)
                checks.write(r, 4, tolerance, formula_money)
                checks.write_formula(r, 5, f'=IF(ABS(D{r+1})<=E{r+1},"OK","FAIL")')
        checks.write("A10", "Overall Model Status", section)
        checks.write_formula("B10", '=IF(COUNTIF(F4:F7,"FAIL")=0,"OK","REVIEW")')
        checks.conditional_format("F4:F7", {"type": "text", "criteria": "containing", "value": "OK", "format": workbook.add_format({"bg_color": "#BFE5D8", "font_color": "#17624D", "bold": True})})
        checks.conditional_format("F4:F7", {"type": "text", "criteria": "containing", "value": "FAIL", "format": workbook.add_format({"bg_color": "#F7C6C7", "font_color": "#8D1B1B", "bold": True})})
        checks.set_column("A:A", 30)
        checks.set_column("B:F", 16)

        dashboard = sheets["Dashboard"]
        dashboard.merge_range("A1:J1", "EQUITYLENS", title)
        dashboard.merge_range("A2:J2", "Explainable financial analysis and valuation | Nasdaq, Inc. (NDAQ)", subtitle)
        dashboard.write("A4", "Company", label); dashboard.merge_range("B4:D4", company.company_name, value)
        dashboard.write("F4", "Ticker", label); dashboard.merge_range("G4:H4", company.ticker, value)
        dashboard.write("A6", "Current Price", label); dashboard.merge_range("B6:D6", "='DCF Model'!B39", value); dashboard.write_formula("B6", "='DCF Model'!B39", per_share)
        dashboard.write("F6", "Fair Value", label); dashboard.write_formula("G6", "='DCF Model'!B38", per_share)
        dashboard.write("A8", "Upside / Downside", label); dashboard.write_formula("B8", "='DCF Model'!B40", pct)
        dashboard.write("F8", "Valuation View", label); dashboard.write_formula("G8", '=IF(B8>10%,"UNDERVALUED",IF(B8<-10%,"OVERVALUED","FAIRLY VALUED"))', value)
        dashboard.write("A10", "Model Status", label); dashboard.write_formula("B10", "='Checks'!B10", value)
        dashboard.write("F10", "Source Fiscal Years", label); dashboard.merge_range("G10:J10", metadata.get("fiscal_years", "Not available"), value)
        dashboard.write("A11", "Price Source", label); dashboard.merge_range("B11:D11", metadata.get("price_source", "Not available"), value)
        dashboard.write("F11", "Price Timestamp", label); dashboard.merge_range("G11:J11", metadata.get("price_timestamp") or "Not available", value)
        dashboard.merge_range("A12:J12", "Key Value Drivers", section)
        drivers = [
            "Revenue growth and durability of recurring data/workflow revenue",
            "EBIT margin execution and integration benefits",
            "Cost of capital and terminal growth assumptions",
            "Debt reduction and cash generation",
        ]
        for i, driver in enumerate(drivers, start=13):
            dashboard.write(i - 1, 0, f"{i-12}.", label)
            dashboard.merge_range(i - 1, 1, i - 1, 9, driver, memo_fmt)
        dashboard.merge_range("A19:J19", "Important Limitation", section)
        limitation = (
            "SAMPLE DATA FALLBACK: historical financial values are illustrative and are not SEC filing facts. "
            "Market price may come from yfinance or manual input. Do not use this fallback output for investment decisions."
            if is_sample_fallback
            else "Historical financial statement inputs come from SEC EDGAR Company Facts. Market price comes from yfinance when available or a manual fallback; Yahoo data may be delayed. XBRL tags, calculated FCF, debt composition, and forecast assumptions should be reviewed before any investment decision."
        )
        dashboard.merge_range("A20:J21", limitation, note)
        dashboard.set_column("A:A", 22)
        dashboard.set_column("B:D", 14)
        dashboard.set_column("E:E", 3)
        dashboard.set_column("F:F", 20)
        dashboard.set_column("G:J", 14)
        dashboard.set_row(0, 34)
        dashboard.freeze_panes(3, 0)

        # Charts use visible, auditable historical and forecast data.
        chart = workbook.add_chart({"type": "line"})
        historical_end_row = 4 + len(raw_data)
        chart.add_series({"name": "Revenue", "categories": f"='Raw Financials'!$A$5:$A${historical_end_row}", "values": f"='Raw Financials'!$B$5:$B${historical_end_row}", "line": {"color": teal, "width": 2.5}})
        chart.set_title({"name": ("Sample Revenue Trend ($mm)" if is_sample_fallback else "SEC-Reported Revenue Trend ($mm)")})
        chart.set_legend({"none": True})
        chart.set_y_axis({"num_format": '$#,##0', "major_gridlines": {"visible": False}})
        chart.set_chartarea({"border": {"none": True}})
        dashboard.insert_chart("A24", chart, {"x_scale": 1.15, "y_scale": 0.95})
        margin_chart = workbook.add_chart({"type": "line"})
        margin_chart.add_series({"name": "EBIT Margin", "categories": f"='Ratio Analysis'!$A$5:$A${historical_end_row}", "values": f"='Ratio Analysis'!$C$5:$C${historical_end_row}", "line": {"color": navy, "width": 2.5}})
        margin_chart.add_series({"name": "FCF Margin", "categories": f"='Ratio Analysis'!$A$5:$A${historical_end_row}", "values": f"='Ratio Analysis'!$E$5:$E${historical_end_row}", "line": {"color": teal, "width": 2.5}})
        margin_chart.set_title({"name": ("Sample Margin Trend" if is_sample_fallback else "SEC-Derived Margin Trend")})
        margin_chart.set_y_axis({"num_format": "0%", "major_gridlines": {"visible": False}})
        margin_chart.set_chartarea({"border": {"none": True}})
        dashboard.insert_chart("F24", margin_chart, {"x_scale": 1.05, "y_scale": 0.95})

        workbook.set_properties({"title": "EquityLens - Nasdaq, Inc. Valuation", "subject": "SEC filing-grounded financial analysis and DCF", "author": "EquityLens"})
    return output
