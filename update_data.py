import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests
from yahooquery import Ticker

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
RESULTS_PATH = BASE / "results.json"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_us_symbols():
    url = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
    text = requests.get(url, timeout=30).text
    rows = []
    for line in text.splitlines()[1:]:
        if not line or line.startswith("File Creation Time"):
            continue
        parts = line.split("|")
        if len(parts) < 2:
            continue
        symbol = parts[0].strip()
        if symbol and "$" not in symbol and "." not in symbol:
            rows.append(symbol)

    other = requests.get("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt", timeout=30).text
    for line in other.splitlines()[1:]:
        if not line or line.startswith("File Creation Time"):
            continue
        parts = line.split("|")
        if len(parts) < 3:
            continue
        symbol = parts[0].strip()
        if symbol and "$" not in symbol and "." not in symbol:
            rows.append(symbol)
    return sorted(set(rows))


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def safe_number(v):
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        return float(v)
    except Exception:
        return None


def process_batch(symbols, cfg):
    t = Ticker(symbols, asynchronous=False, formatted=False, max_workers=4, timeout=30)
    price_data = t.price or {}
    summary_data = t.summary_detail or {}
    quote_type = t.quote_type or {}
    history = t.history(period=cfg.get("history_period", "400d"), interval="1d")

    out = []
    if history is None or len(history) == 0:
        return out

    if isinstance(history.index, pd.MultiIndex):
        history = history.reset_index()
    else:
        return out

    history["date"] = pd.to_datetime(history["date"])

    for symbol in symbols:
        p = price_data.get(symbol, {}) if isinstance(price_data, dict) else {}
        s = summary_data.get(symbol, {}) if isinstance(summary_data, dict) else {}
        q = quote_type.get(symbol, {}) if isinstance(quote_type, dict) else {}

        exchange = p.get("exchangeName") or q.get("exchange") or q.get("exchangeName")
        if cfg.get("allowed_exchange_names") and exchange not in cfg["allowed_exchange_names"]:
            continue

        market_cap = safe_number(s.get("marketCap") or p.get("marketCap"))
        if market_cap is None or market_cap < cfg["market_cap_min"]:
            continue

        sub = history[history["symbol"] == symbol].sort_values("date")
        if len(sub) < 252:
            continue

        closes = sub["close"].dropna().tolist()
        if len(closes) < 200:
            continue

        current_price = safe_number(closes[-1])
        price_2m_ago = safe_number(closes[-43]) if len(closes) >= 43 else None
        if not current_price or not price_2m_ago:
            continue

        ma50 = safe_number(pd.Series(closes[-50:]).mean()) if len(closes) >= 50 else None
        ma200 = safe_number(pd.Series(closes[-200:]).mean()) if len(closes) >= 200 else None
        high_52w = safe_number(max(closes[-252:])) if len(closes) >= 252 else None
        if not ma50 or not ma200 or not high_52w:
            continue

        return_2m_pct = (current_price / price_2m_ago - 1) * 100
        if return_2m_pct <= cfg["min_2m_return_pct"]:
            continue

        if cfg.get("require_price_above_50ma", True) and current_price <= ma50:
            continue

        if cfg.get("require_50ma_above_200ma", True) and ma50 <= ma200:
            continue

        distance_to_52w_high_pct = (high_52w - current_price) / high_52w * 100
        if distance_to_52w_high_pct > cfg["max_pct_below_52w_high"]:
            continue

        out.append({
            "symbol": symbol,
            "company": q.get("longName") or p.get("shortName") or symbol,
            "sector": q.get("sector") or "",
            "exchange": exchange,
            "market_cap": market_cap,
            "current_price": current_price,
            "ma50": round(ma50, 2),
            "ma200": round(ma200, 2),
            "high_52w": round(high_52w, 2),
            "distance_to_52w_high_pct": round(distance_to_52w_high_pct, 2),
            "return_2m_pct": round(return_2m_pct, 2)
        })
    return out


def main():
    cfg = load_config()
    symbols = load_us_symbols()
    batches = list(chunked(symbols, 80))
    results = []

    with ThreadPoolExecutor(max_workers=cfg.get("max_workers", 8)) as ex:
        futures = [ex.submit(process_batch, batch, cfg) for batch in batches]
        for fut in as_completed(futures):
            try:
                results.extend(fut.result())
            except Exception:
                pass

    results.sort(key=lambda x: x.get("return_2m_pct", 0), reverse=True)
    payload = {
        "generated_at": pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M UTC"),
        "rules": {
            "market_cap_min": cfg["market_cap_min"],
            "min_2m_return_pct": cfg["min_2m_return_pct"],
            "max_pct_below_52w_high": cfg["max_pct_below_52w_high"],
            "require_price_above_50ma": cfg["require_price_above_50ma"],
            "require_50ma_above_200ma": cfg["require_50ma_above_200ma"],
        },
        "results": results,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
