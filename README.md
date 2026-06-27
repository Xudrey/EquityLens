# EquityLens

EquityLens is an SEC filing-grounded financial analysis and valuation project for Nasdaq, Inc. (`NDAQ`). It pulls annual XBRL facts from SEC EDGAR, calculates historical ratios, runs a five-year DCF, sensitivity analysis, a Python-native Monte Carlo valuation simulation, generates a rule-based investment memo, and exports an auditable Excel workbook.

> EquityLens is an educational project, not investment advice. SEC filing data can contain taxonomy changes, restatements, missing concepts, and company-specific presentation differences.

## Active Data Mode

EquityLens prefers **SEC Filing Data** in the Streamlit app and command-line report generator.

The Streamlit sidebar includes `Use Sample Data Fallback`. When enabled, an SEC network failure loads the original illustrative CSV and displays a prominent sample-data warning. The app never labels sample values as SEC data.

SEC Company Facts supplies filing-based financial statements. EquityLens uses yfinance for the latest available NDAQ market price and retains manual entry as a fallback.

Yahoo prices may be delayed, may reflect the latest available close rather than a real-time exchange quote, and may fail when network access is blocked.

## Monte Carlo Simulation

Monte Carlo is an optional uncertainty layer on top of the base DCF. It does **not** replace the base-case valuation.

The first implementation is intentionally simple:

- Uses Python directly with `pandas` and `numpy`.
- Does not use Argo directly in Python.
- Treats Argo only as a conceptual reference for spreadsheet-style simulation workflows.
- Starts from the normal base-case DCF and keeps that result separate from the simulated distribution.
- Identifies and ranks value drivers using simple valuation-impact sensitivity plus historical/business-risk uncertainty.
- Draws key assumptions from editable distribution specs.
- Explains why each distribution was chosen and what business risk it represents.
- Applies guardrails so WACC stays above terminal growth, margins stay realistic, FCF margin does not unrealistically exceed EBIT margin, and negative equity values are flagged.
- Returns simulation detail, summary percentiles, probability above/below current price, value-driver tables, constraint notes, and a plain-English explanation.
- Exports simulation outputs to Excel when the Streamlit workbook export is prepared.

Default NDAQ simulation distributions live in `src/monte_carlo_dcf.py` and are easy to edit.

## SEC Data Source

Nasdaq is mapped to:

```text
Ticker: NDAQ
CIK: 0001120193
Company Facts API: https://data.sec.gov/api/xbrl/companyfacts/CIK0001120193.json
```

`src/sec_data.py`:

- Sends a declared `User-Agent` header.
- Filters for annual `10-K` and `10-K/A` facts.
- Rejects quarterly-duration observations.
- Prefers fiscal-year facts and standardized units.
- Keeps five to ten recent fiscal years.
- Chooses later-filed annual facts when the same period is restated.
- Converts USD and share values to millions.
- Calculates free cash flow as operating cash flow minus absolute capex.
- Combines current and noncurrent debt when no suitable aggregate exists.
- Records tags, accessions, filing dates, fallback methods, and quality warnings.
- Caches the public SEC JSON for six hours to reduce unnecessary EDGAR traffic.

Set a real project contact before accessing EDGAR:

```bash
export SEC_USER_AGENT="EquityLens academic portfolio project your-email@example.com"
```

The SEC currently permits no more than 10 automated requests per second. EquityLens performs one Company Facts request and uses a local cache.

## Project Structure

```text
app/                    Streamlit interface
data/cache/             Locally cached SEC response, ignored by Git
data/ndaq_sample_financials.csv  Illustrative emergency fallback
notebooks/              Optional exploration
src/sec_data.py         SEC fetch, cleaning, tag selection, and audit trail
src/market_data.py      yfinance market-price fetch and graceful fallback result
src/monte_carlo_dcf.py  Python-native Monte Carlo DCF simulation
src/                    Analysis, DCF, sensitivity, memo, and Excel modules
outputs/                Generated workbooks
tests/                  Calculation and offline SEC-ingestion tests
```

## Setup

Python 3.10 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The first SEC run requires an internet connection. Later runs can use the cached public SEC response if EDGAR is temporarily unavailable. Automatic market pricing also requires access to Yahoo Finance through yfinance.

## Run the Streamlit App

```bash
export SEC_USER_AGENT="EquityLens academic portfolio project your-email@example.com"
python3 -m streamlit run app/streamlit_app.py
```

If Streamlit reports an outdated function signature after an upgrade, stop the running server and restart it with the command above so Python reloads the updated modules.

If you see `cannot import name 'test_sec_connection'`, fully stop the existing Streamlit server before restarting. The app now also handles an older cached `sec_data` module without crashing and shows this restart guidance in the sidebar.

Then:

1. Click `Test SEC Connection` to inspect the live SEC URL, User-Agent state, and HTTP result.
2. Leave `Use Sample Data Fallback` enabled if you want the app to remain usable during an SEC outage.
3. Leave `Auto-fetch market price` enabled to use yfinance.
4. If Yahoo is unavailable, enter the current NDAQ price in the manual fallback field.
5. Select five to ten fiscal years and adjust the DCF assumptions.
6. Leave `Run Monte Carlo simulation` enabled if you want valuation percentiles and probability above market price.
7. Review the source badge, price timestamp, quality notes, and simulation output before exporting.

## Troubleshooting

### Missing yfinance

If the app reports that yfinance is unavailable, install the complete project dependencies inside the active environment:

```bash
python3 -m pip install -r requirements.txt
```

You can still disable automatic pricing and enter the market price manually.

### Missing SEC_USER_AGENT

SEC requests should identify the application and a real contact address:

```bash
export SEC_USER_AGENT="EquityLens academic portfolio project your-email@example.com"
```

Restart Streamlit after setting the variable. The `Test SEC Connection` diagnostics show whether the variable was found.

### SEC Network Failure

Use `Test SEC Connection` in the sidebar. It displays:

- SEC Company Facts URL
- whether `SEC_USER_AGENT` was configured
- HTTP status code
- response preview for failed HTTP responses
- underlying network error

Successful responses are saved to `data/cache/ndaq_companyfacts.json`. If the live request later fails, EquityLens can use that cached SEC response. If no cache exists, enable `Use Sample Data Fallback` to run in clearly labeled demo mode.

### Local App Command

From the project root:

```bash
python3 -m streamlit run app/streamlit_app.py
```

## Generate Excel Directly

```bash
export SEC_USER_AGENT="EquityLens academic portfolio project your-email@example.com"
python -m src.main --years 7
```

The CLI also uses yfinance automatically. Supply a manual override when needed:

```bash
python -m src.main --share-price 75.00 --years 7
```

The workbook is written to `outputs/EquityLens_NDAQ_MVP.xlsx` and contains:

- Dashboard
- Source Data
- Raw Financials
- Ratio Analysis
- DCF Model
- Sensitivity Analysis
- Monte Carlo Summary
- Monte Carlo Results
- Monte Carlo Sensitivity
- Monte Carlo Drivers
- Monte Carlo Explanation
- Investment Memo Draft
- SEC Tags Used
- Data Quality Notes
- Checks

## XBRL Limitations

- Company Facts includes standardized taxonomy concepts, not every Nasdaq-specific extension.
- Nasdaq reports gross revenue and revenue less transaction-based expenses. EquityLens uses the best available standardized total-revenue concept and discloses the tag.
- Historical facts may be repeated or restated in later 10-Ks.
- Debt can be reported as aggregate, current/noncurrent components, short-term borrowings, or finance-lease-inclusive balances.
- Combined cash and restricted cash may not equal cash freely available for the DCF equity bridge.
- Weighted-average diluted shares and period-end outstanding shares are not economically identical.
- Nasdaq's 2022 stock split can affect historical share and EPS comparability.
- The 2023 Adenza acquisition created a material break in revenue, amortization, debt, and margins.
- A pre-tax-income fallback is only an EBIT proxy and is explicitly flagged.
- Free cash flow is a calculated non-GAAP metric, not a directly reported SEC line item.
- yfinance is an unofficial Yahoo Finance client intended for research and educational use; price availability and timeliness are not guaranteed.

Every exported workbook includes the selected facts, SEC tags, accession numbers, and data-quality notes so these limitations are visible rather than hidden.

## Tests

```bash
pytest
```

The SEC tests use an offline Company Facts fixture shape. This avoids repeatedly contacting EDGAR and verifies annual filtering, unit scaling, quarterly rejection, debt aggregation, and FCF construction.

## Roadmap

- Extract 10-K business-description and risk-factor text.
- Add filing-to-filing change detection.
- Add peer comparison for ICE, CME, CBOE, and MSCI after NDAQ ingestion is stable.
- Add an OpenAI-generated memo only after the filing pipeline is validated.
- Add richer Monte Carlo controls, including optional correlated assumption draws and peer-informed distribution ranges.
