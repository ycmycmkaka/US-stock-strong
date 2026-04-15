import json
import time
from pathlib import Path

import pandas as pd
import requests
from yahooquery import Ticker


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
RESULTS_PATH = BASE_DIR / "results.json"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_us_symbols():
    url1 = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
    r1 = requests.get(url1, timeout=30)
    r1.raise_for_status()
    df1 = pd.read_csv(pd.io.common.StringIO(r1.text), sep="|")
    df1 = df1[df1["Symbol"] != "File Creation Time"]
    df1 = df1[["Symbol"]].copy()
    df1["exchange"] = "NASDAQ"

    url2 = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
    r2 = requests.get(url2, timeout=30)
    r2.raise_for_status()
    df2 = pd.read_csv(pd.io.common.StringIO(r2.text), sep="|")
    df2 = df2[df2["ACT Symbol"] != "File Creation Time"]
    df2 = df2.rename(columns={"ACT Symbol": "Symbol", "Exchange": "exchange"})
    df2 = df2[["Symbol", "exchange"]].copy()

    exchange_map = {
        "N": "NYSE",
        "A": "AMEX",
        "P": "NYSE Arca",
        "Z": "BATS",
        "V": "IEX",
    }
    df2["exchange"] = df2["exchange"].map(exchange_map).fillna(df2["exchange"])

    df = pd.concat([df1, df2], ignore_index=True)
    df = df.dropna()
    df = df[~df["Symbol"].astype(str).str.contains(r"[\^\$]", regex=True)]
    df = df[~df["Symbol"].astype(str).str.contains(r"\.", regex=True)]
    df = df.drop_duplicates(subset=["Symbol"]).reset_index(drop=True)
    return df


def safe_pct_return(current_price, past_price):
    if past_price is None or pd.isna(past_price) or past_price <= 0:
        return None
    return (current_price / past_price - 1) * 100


def get_price_at_or_before(series: pd.Series, target_date: pd.Timestamp):
    if series.empty:
        return None
    s = series[series.index <= target_date]
    if s.empty:
        return None
    return float(s.iloc[-1])


def get_price_history(symbols):
    ticker = Ticker(symbols, asynchronous=True, max_workers=8)
    history = ticker.history(period="14mo", interval="1d")
    price = ticker.price
    return history, price


def get_benchmark_returns(symbol: str):
    t = Ticker(symbol, asynchronous=False)
    hist = t.history(period="6mo", interval="1d")

    if hist is None or len(hist) == 0:
        raise ValueError(f"Cannot fetch benchmark history for {symbol}")

    hist = hist.reset_index()
    hist["date"] = pd.to_datetime(hist["date"], utc=True).dt.tz_convert(None)
    hist = hist.sort_values("date")
    closes = hist.set_index("date")["close"].dropna()

    if closes.empty:
        raise ValueError(f"No close data for benchmark {symbol}")

    latest_date = closes.index.max()
    latest_close = float(closes.iloc[-1])

    five_days_ago = latest_date - pd.Timedelta(days=7)
    twenty_days_ago = latest_date - pd.Timedelta(days=30)

    price_5d = get_price_at_or_before(closes, five_days_ago)
    price_20d = get_price_at_or_before(closes, twenty_days_ago)

    return {
        "latest_close": latest_close,
        "five_day_return_pct": safe_pct_return(latest_close, price_5d),
        "twenty_day_return_pct": safe_pct_return(latest_close, price_20d),
    }


def build_results():
    config = load_config()
    benchmark_symbol = config["benchmark_symbol"]

    symbols_df = fetch_us_symbols()
    symbols = symbols_df["Symbol"].tolist()

    benchmark = get_benchmark_returns(benchmark_symbol)
    spy_5d = benchmark["five_day_return_pct"]
    spy_20d = benchmark["twenty_day_return_pct"]

    batch_size = 80
    rows = []

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]

        try:
            history, summary = get_price_history(batch)
        except Exception:
            time.sleep(1)
            continue

        history_df = history.reset_index() if hasattr(history, "reset_index") else pd.DataFrame()
        if history_df.empty:
            continue

        history_df["date"] = pd.to_datetime(history_df["date"], utc=True).dt.tz_convert(None)
        history_df = history_df.sort_values(["symbol", "date"])

        for symbol in batch:
            try:
                info = summary.get(symbol, {})
                if not isinstance(info, dict):
                    continue

                market_cap = info.get("marketCap")
                short_name = info.get("shortName") or info.get("longName") or symbol
                exchange = info.get("exchangeName") or info.get("fullExchangeName") or ""

                if market_cap is None or market_cap < config["market_cap_min"]:
                    continue

                stock_hist = history_df[history_df["symbol"] == symbol].copy()
                if stock_hist.empty:
                    continue

                closes = stock_hist.set_index("date")["close"].dropna()
                if len(closes) < 260:
                    continue

                latest_date = closes.index.max()
                recent_close = float(closes.iloc[-1])

                five_days_ago = latest_date - pd.Timedelta(days=7)
                twenty_days_ago = latest_date - pd.Timedelta(days=30)

                price_5d = get_price_at_or_before(closes, five_days_ago)
                price_20d = get_price_at_or_before(closes, twenty_days_ago)

                return_5d = safe_pct_return(recent_close, price_5d)
                return_20d = safe_pct_return(recent_close, price_20d)

                if return_5d is None or return_20d is None:
                    continue

                rs_5d = return_5d - spy_5d
                rs_20d = return_20d - spy_20d

                trailing_52w = closes.tail(252)
                if trailing_52w.empty:
                    continue

                high_52w = float(trailing_52w.max())
                dist_from_52w_high_pct = ((recent_close / high_52w) - 1) * 100

                if rs_5d < config["rs_5d_vs_spy_min_pct"]:
                    continue

                if rs_20d < config["rs_20d_vs_spy_min_pct"]:
                    continue

                if abs(dist_from_52w_high_pct) > config["max_dist_from_52w_high_pct"]:
                    continue

                rows.append(
                    {
                        "symbol": symbol,
                        "company": short_name,
                        "exchange": exchange,
                        "market_cap": market_cap,
                        "recent_close": round(recent_close, 2),
                        "five_day_return_pct": round(return_5d, 1),
                        "twenty_day_return_pct": round(return_20d, 1),
                        "spy_five_day_return_pct": round(spy_5d, 1),
                        "spy_twenty_day_return_pct": round(spy_20d, 1),
                        "rs_5d_vs_spy_pct": round(rs_5d, 1),
                        "rs_20d_vs_spy_pct": round(rs_20d, 1),
                        "high_52w": round(high_52w, 2),
                        "dist_from_52w_high_pct": round(dist_from_52w_high_pct, 1),
                    }
                )
            except Exception:
                continue

    rows = sorted(rows, key=lambda x: x["rs_20d_vs_spy_pct"], reverse=True)

    output = {
        "generated_at": pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M UTC"),
        "rules": {
            "market_cap_min": config["market_cap_min"],
            "benchmark_symbol": benchmark_symbol,
            "rs_5d_vs_spy_min_pct": config["rs_5d_vs_spy_min_pct"],
            "rs_20d_vs_spy_min_pct": config["rs_20d_vs_spy_min_pct"],
            "max_dist_from_52w_high_pct": config["max_dist_from_52w_high_pct"],
            "spy_five_day_return_pct": round(spy_5d, 1),
            "spy_twenty_day_return_pct": round(spy_20d, 1),
        },
        "results": rows,
    }

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    build_results()
