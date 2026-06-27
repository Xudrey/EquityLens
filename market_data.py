"""Market price fetcher with manual fallback support."""

from datetime import datetime, timezone
from typing import Any


def get_current_price(ticker: str) -> dict[str, Any]:
    """Fetch latest available market price from yfinance without crashing."""
    try:
        import yfinance as yf
    except Exception as exc:
        return {
            "ticker": ticker,
            "current_price": None,
            "price_source": "manual input required",
            "price_timestamp": None,
            "error_message": f"yfinance is unavailable: {exc}",
        }
    try:
        stock = yf.Ticker(ticker)
        info = stock.fast_info
        price = info.get("last_price") or info.get("previous_close")
        if price is None:
            history = stock.history(period="5d")
            if not history.empty:
                price = float(history["Close"].dropna().iloc[-1])
        if price is None:
            raise ValueError("No price returned by yfinance.")
        return {
            "ticker": ticker,
            "current_price": float(price),
            "price_source": "yfinance",
            "price_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "error_message": None,
        }
    except Exception as exc:
        return {
            "ticker": ticker,
            "current_price": None,
            "price_source": "manual input required",
            "price_timestamp": None,
            "error_message": str(exc),
        }
