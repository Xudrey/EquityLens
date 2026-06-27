# EquityLens Streamlit App

The EquityLens web interface lives in `streamlit_app.py`, prefers NDAQ annual facts from SEC EDGAR, and can use clearly labeled sample data when the SEC connection fails.

Run it from the project root:

```bash
python3 -m streamlit run app/streamlit_app.py
```

The app auto-fetches the latest available NDAQ price with yfinance by default. Disable the toggle or use the manual field if Yahoo market data is unavailable. Yahoo prices may be delayed or reflect the latest available close.
