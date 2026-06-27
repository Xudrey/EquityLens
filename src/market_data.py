"""Best-effort current market price retrieval for EquityLens."""

from __future__ import annotations

import math
from typing import Any


def _result(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "current_price": None,
        "price_source": None,
        "price_timestamp": None,
        "error_message": None,
    }


def _latest_close(history: Any) -> tuple[float, str | None] | None:
    """Return the latest positive close and its timestamp from a history frame."""
    if history is None or getattr(history, "empty", True) or "Close" not in history:
        return None
    closes = history["Close"].dropna()
    if closes.empty:
        return None
    price = float(closes.iloc[-1])
    if not math.isfinite(price) or price <= 0:
        return None
    timestamp = closes.index[-1]
    if hasattr(timestamp, "isoformat"):
        timestamp = timestamp.isoformat()
    elif timestamp is not None:
        timestamp = str(timestamp)
    return price, timestamp


def get_current_price(ticker: str) -> dict[str, Any]:
    """Fetch the latest available price from yfinance without raising errors."""
    symbol = str(ticker).strip().upper()
    result = _result(symbol)
    if not symbol:
        result["error_message"] = "Ticker symbol is required."
        return result

    try:
        import yfinance as yf
    except (ImportError, ModuleNotFoundError) as exc:
        result["error_message"] = f"yfinance is unavailable: {exc}"
        return result

    try:
        security = yf.Ticker(symbol)
    except Exception as exc:
        result["error_message"] = f"Unable to initialize yfinance for {symbol}: {exc}"
        return result

    errors: list[str] = []
    attempts = [
        ("intraday", {"period": "1d", "interval": "1m"}),
        ("daily", {"period": "5d", "interval": "1d"}),
    ]
    for label, options in attempts:
        try:
            history = security.history(
                auto_adjust=False,
                prepost=False,
                actions=False,
                timeout=10,
                **options,
            )
            latest = _latest_close(history)
            if latest:
                result.update(
                    {
                        "current_price": latest[0],
                        "price_source": "yfinance",
                        "price_timestamp": latest[1],
                    }
                )
                return result
            errors.append(f"{label} history contained no valid closing price")
        except Exception as exc:
            errors.append(f"{label} history failed: {exc}")

    result["error_message"] = f"No valid yfinance price was available for {symbol}. " + "; ".join(errors)
    return result
