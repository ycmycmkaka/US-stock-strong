import json
import time
from pathlib import Path
from io import StringIO

import pandas as pd
import requests
from yahooquery import Ticker


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
RESULTS_PATH = BASE_DIR / "results.json"


# ============================================================
# CONFIG
# ============================================================

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# STOCK SYMBOLS
# ============================================================

def fetch_us_symbols():

    # NASDAQ
    nasdaq_url = (
        "https://www.nasdaqtrader.com/dynamic/"
        "SymDir/nasdaqlisted.txt"
    )

    r = requests.get(nasdaq_url, timeout=30)
    r.raise_for_status()

    nasdaq = pd.read_csv(
        StringIO(r.text),
        sep="|"
    )

    nasdaq = nasdaq[
        nasdaq["Symbol"] != "File Creation Time"
    ]

    nasdaq = nasdaq[["Symbol"]].copy()
    nasdaq["exchange"] = "NASDAQ"

    # NYSE / AMEX / others
    other_url = (
        "https://www.nasdaqtrader.com/dynamic/"
        "SymDir/otherlisted.txt"
    )

    r = requests.get(other_url, timeout=30)
    r.raise_for_status()

    other = pd.read_csv(
        StringIO(r.text),
        sep="|"
    )

    other = other[
        other["ACT Symbol"] != "File Creation Time"
    ]

    other = other.rename(
        columns={
            "ACT Symbol": "Symbol",
            "Exchange": "exchange"
        }
    )

    other = other[
        ["Symbol", "exchange"]
    ].copy()

    exchange_map = {
        "N": "NYSE",
        "A": "AMEX",
        "P": "NYSE Arca",
        "Z": "BATS",
        "V": "IEX",
    }

    other["exchange"] = (
        other["exchange"]
        .map(exchange_map)
        .fillna(other["exchange"])
    )

    df = pd.concat(
        [nasdaq, other],
        ignore_index=True
    )

    df = df.dropna(subset=["Symbol"])

    # 排除特殊 ticker
    df = df[
        ~df["Symbol"]
        .astype(str)
        .str.contains(r"[\^\$]", regex=True)
    ]

    df = df[
        ~df["Symbol"]
        .astype(str)
        .str.contains(r"\.", regex=True)
    ]

    df = (
        df.drop_duplicates(subset=["Symbol"])
        .reset_index(drop=True)
    )

    return df


# ============================================================
# HELPERS
# ============================================================

def safe_pct_return(current_price, past_price):

    if (
        past_price is None
        or pd.isna(past_price)
        or past_price <= 0
    ):
        return None

    return (
        (current_price / past_price) - 1
    ) * 100


def get_price_at_or_before(
    series,
    target_date
):

    if series.empty:
        return None

    temp = series[
        series.index <= target_date
    ]

    if temp.empty:
        return None

    return float(temp.iloc[-1])


# ============================================================
# DOWNLOAD PRICE HISTORY
# ============================================================

def get_price_history(symbols):

    ticker = Ticker(
        symbols,
        asynchronous=True,
        max_workers=8
    )

    history = ticker.history(
        period="3y",
        interval="1d"
    )

    price = ticker.price

    return history, price


# ============================================================
# SPY RETURNS
# ============================================================

def get_benchmark_returns(symbol):

    ticker = Ticker(
        symbol,
        asynchronous=False
    )

    hist = ticker.history(
        period="6mo",
        interval="1d"
    )

    if hist is None or len(hist) == 0:
        raise ValueError(
            f"Cannot fetch benchmark history for {symbol}"
        )

    hist = hist.reset_index()

    hist["date"] = (
        pd.to_datetime(
            hist["date"],
            utc=True
        )
        .dt
        .tz_convert(None)
    )

    hist = hist.sort_values("date")

    closes = (
        hist
        .set_index("date")["close"]
        .dropna()
    )

    if closes.empty:
        raise ValueError(
            f"No close data for {symbol}"
        )

    latest_date = closes.index.max()
    latest_close = float(closes.iloc[-1])

    price_5d = get_price_at_or_before(
        closes,
        latest_date - pd.Timedelta(days=7)
    )

    price_20d = get_price_at_or_before(
        closes,
        latest_date - pd.Timedelta(days=30)
    )

    return {
        "latest_close": latest_close,

        "five_day_return_pct":
            safe_pct_return(
                latest_close,
                price_5d
            ),

        "twenty_day_return_pct":
            safe_pct_return(
                latest_close,
                price_20d
            )
    }


# ============================================================
# MOMENTUM SCREENER
# ============================================================

def build_momentum_row(
    symbol,
    info,
    stock_hist,
    config,
    spy_5d,
    spy_20d
):

    rules = config["momentum"]

    market_cap = info.get("marketCap")

    if (
        market_cap is None
        or market_cap < rules["market_cap_min"]
    ):
        return None

    df = (
        stock_hist
        .sort_values("date")
        .copy()
    )

    closes = (
        df
        .set_index("date")["close"]
        .dropna()
    )

    if len(closes) < 260:
        return None

    latest_date = closes.index.max()
    recent_close = float(closes.iloc[-1])

    price_5d = get_price_at_or_before(
        closes,
        latest_date - pd.Timedelta(days=7)
    )

    price_20d = get_price_at_or_before(
        closes,
        latest_date - pd.Timedelta(days=30)
    )

    return_5d = safe_pct_return(
        recent_close,
        price_5d
    )

    return_20d = safe_pct_return(
        recent_close,
        price_20d
    )

    if (
        return_5d is None
        or return_20d is None
    ):
        return None

    rs_5d = return_5d - spy_5d
    rs_20d = return_20d - spy_20d

    trailing_52w = df.tail(252)

    high_52w = float(
        trailing_52w["high"]
        .dropna()
        .max()
    )

    if (
        pd.isna(high_52w)
        or high_52w <= 0
    ):
        return None

    dist_from_52w_high_pct = (
        (recent_close / high_52w) - 1
    ) * 100

    if (
        rs_5d
        < rules["rs_5d_vs_spy_min_pct"]
    ):
        return None

    if (
        rs_20d
        < rules["rs_20d_vs_spy_min_pct"]
    ):
        return None

    if (
        abs(dist_from_52w_high_pct)
        > rules["max_dist_from_52w_high_pct"]
    ):
        return None

    return {
        "symbol": symbol,

        "company":
            info.get("shortName")
            or info.get("longName")
            or symbol,

        "exchange":
            info.get("exchangeName")
            or info.get("fullExchangeName")
            or "",

        "market_cap": market_cap,

        "recent_close":
            round(recent_close, 2),

        "five_day_return_pct":
            round(return_5d, 1),

        "twenty_day_return_pct":
            round(return_20d, 1),

        "spy_five_day_return_pct":
            round(spy_5d, 1),

        "spy_twenty_day_return_pct":
            round(spy_20d, 1),

        "rs_5d_vs_spy_pct":
            round(rs_5d, 1),

        "rs_20d_vs_spy_pct":
            round(rs_20d, 1),

        "high_52w":
            round(high_52w, 2),

        "dist_from_52w_high_pct":
            round(dist_from_52w_high_pct, 1)
    }


# ============================================================
# BREAKOUT + HIGH CONSOLIDATION SCREENER
# ============================================================

def build_breakout_row(
    symbol,
    info,
    stock_hist,
    config
):

    rules = config["breakout_setup"]

    # ========================================================
    # 1. MARKET CAP
    # ========================================================

    market_cap = info.get("marketCap")

    if (
        market_cap is None
        or market_cap < rules["market_cap_min"]
    ):
        return None

    required_columns = {
        "date",
        "close",
        "high",
        "volume"
    }

    if not required_columns.issubset(
        stock_hist.columns
    ):
        return None

    df = (
        stock_hist
        .sort_values("date")
        .copy()
    )

    df = df.dropna(
        subset=[
            "close",
            "volume"
        ]
    )

    df = df[
        (df["close"] > 0)
        & (df["volume"] >= 0)
    ].copy()

    if df.empty:
        return None

    # ========================================================
    # LOAD RULES
    # ========================================================

    exclude_days = int(
        rules.get(
            "exclude_recent_trading_days",
            60
        )
    )

    breakout_window_days = int(
        rules.get(
            "breakout_window_days",
            60
        )
    )

    latest_close_min_pct = float(
        rules.get(
            "latest_close_min_pct",
            0
        )
    )

    latest_close_max_pct = float(
        rules.get(
            "latest_close_max_pct",
            8
        )
    )

    recent_window_max_extension_pct = float(
        rules.get(
            "recent_window_max_extension_pct",
            10
        )
    )

    consolidation_days = int(
        rules.get(
            "consolidation_days",
            20
        )
    )

    consolidation_range_max_pct = float(
        rules.get(
            "consolidation_range_max_pct",
            10
        )
    )

    consolidation_avg_close_min_pct = float(
        rules.get(
            "consolidation_avg_close_min_pct",
            0
        )
    )

    hold_days = int(
        rules.get(
            "hold_days",
            10
        )
    )

    hold_required_days = int(
        rules.get(
            "hold_required_days",
            8
        )
    )

    max_pullback_from_peak_pct = float(
        rules.get(
            "max_pullback_from_peak_pct",
            8
        )
    )

    ma_days = int(
        rules.get(
            "ma_days",
            200
        )
    )

    dollar_volume_days = int(
        rules.get(
            "avg_dollar_volume_days",
            10
        )
    )

    avg_dollar_volume_min = float(
        rules.get(
            "avg_dollar_volume_min",
            20000000
        )
    )

    min_history = max(
        ma_days,
        exclude_days + 60,
        breakout_window_days,
        consolidation_days,
        hold_days,
        dollar_volume_days
    )

    if len(df) < min_history:
        return None

    recent_close = float(
        df.iloc[-1]["close"]
    )

    # ========================================================
    # 2. MA200
    # ========================================================

    ma200 = float(
        df["close"]
        .tail(ma_days)
        .mean()
    )

    if recent_close <= ma200:
        return None

    # ========================================================
    # 3. OLD 3-YEAR HIGH
    #
    # 過去3年最高收市價
    # 排除最近60個交易日
    # ========================================================

    if exclude_days > 0:
        old_window = (
            df.iloc[:-exclude_days]
            .copy()
        )
    else:
        old_window = df.copy()

    old_window = (
        old_window
        .dropna(subset=["close"])
    )

    if old_window.empty:
        return None

    old_high_idx = (
        old_window["close"]
        .idxmax()
    )

    old_high = float(
        old_window.loc[
            old_high_idx,
            "close"
        ]
    )

    old_high_date = (
        pd.Timestamp(
            old_window.loc[
                old_high_idx,
                "date"
            ]
        )
        .strftime("%Y-%m-%d")
    )

    if (
        pd.isna(old_high)
        or old_high <= 0
    ):
        return None

    # ========================================================
    # 4. LATEST PRICE DISTANCE
    #
    # 最新收市：
    # 舊頂 0% ～ +8%
    # ========================================================

    distance_pct = (
        (recent_close / old_high) - 1
    ) * 100

    if distance_pct < latest_close_min_pct:
        return None

    if distance_pct > latest_close_max_pct:
        return None

    # ========================================================
    # 5. RECENT 60-DAY BREAKOUT
    #
    # 最近60日至少一次：
    # Close > 舊頂
    # ========================================================

    recent_breakout_window = (
        df.tail(
            breakout_window_days
        )
        .copy()
    )

    breakout_rows = (
        recent_breakout_window[
            recent_breakout_window["close"]
            > old_high
        ]
        .copy()
    )

    if breakout_rows.empty:
        return None

    first_breakout = breakout_rows.iloc[0]

    first_breakout_date_ts = pd.Timestamp(
        first_breakout["date"]
    )

    first_breakout_date = (
        first_breakout_date_ts
        .strftime("%Y-%m-%d")
    )

    first_breakout_close = float(
        first_breakout["close"]
    )

    # ========================================================
    # 6. RECENT 60-DAY MAX EXTENSION
    #
    # 最近60日最高收市：
    # 不可以高過舊頂 +10%
    # ========================================================

    recent_window_peak_close = float(
        recent_breakout_window["close"]
        .max()
    )

    recent_window_peak_idx = (
        recent_breakout_window["close"]
        .idxmax()
    )

    recent_window_peak_date = (
        pd.Timestamp(
            recent_breakout_window.loc[
                recent_window_peak_idx,
                "date"
            ]
        )
        .strftime("%Y-%m-%d")
    )

    recent_window_extension_pct = (
        (
            recent_window_peak_close
            / old_high
        ) - 1
    ) * 100

    if (
        recent_window_extension_pct
        > recent_window_max_extension_pct
    ):
        return None

    # ========================================================
    # 7. 20-DAY HIGH CONSOLIDATION
    #
    # 目的：
    # 真正搵「高位橫行整固」
    #
    # 最近20日：
    # (最高 Close - 最低 Close)
    # / 最低 Close
    # <= 10%
    # ========================================================

    consolidation = (
        df.tail(
            consolidation_days
        )
        .copy()
    )

    if len(consolidation) < consolidation_days:
        return None

    consolidation_high_close = float(
        consolidation["close"].max()
    )

    consolidation_low_close = float(
        consolidation["close"].min()
    )

    consolidation_avg_close = float(
        consolidation["close"].mean()
    )

    if consolidation_low_close <= 0:
        return None

    consolidation_range_pct = (
        (
            consolidation_high_close
            - consolidation_low_close
        )
        / consolidation_low_close
    ) * 100

    if (
        consolidation_range_pct
        > consolidation_range_max_pct
    ):
        return None

    # ========================================================
    # 8. 20-DAY AVERAGE CLOSE
    #
    # 最近20日平均 Close
    # 必須 >= 舊頂
    # ========================================================

    consolidation_avg_vs_old_high_pct = (
        (
            consolidation_avg_close
            / old_high
        ) - 1
    ) * 100

    if (
        consolidation_avg_vs_old_high_pct
        < consolidation_avg_close_min_pct
    ):
        return None

    # ========================================================
    # 9. POST-BREAKOUT PEAK
    # ========================================================

    post_breakout = (
        df[
            df["date"]
            >= first_breakout_date_ts
        ]
        .copy()
    )

    if post_breakout.empty:
        return None

    post_breakout_peak_close = float(
        post_breakout["close"]
        .max()
    )

    post_breakout_peak_idx = (
        post_breakout["close"]
        .idxmax()
    )

    post_breakout_peak_date = (
        pd.Timestamp(
            post_breakout.loc[
                post_breakout_peak_idx,
                "date"
            ]
        )
        .strftime("%Y-%m-%d")
    )

    max_extension_pct = (
        (
            post_breakout_peak_close
            / old_high
        ) - 1
    ) * 100

    # ========================================================
    # 10. PULLBACK FROM PEAK
    #
    # 由突破後最高收市
    # 回撤不可以超過8%
    # ========================================================

    pullback_from_peak_pct = (
        (
            recent_close
            / post_breakout_peak_close
        ) - 1
    ) * 100

    if (
        pullback_from_peak_pct
        < -max_pullback_from_peak_pct
    ):
        return None

    # ========================================================
    # 11. HOLD ABOVE OLD HIGH
    #
    # 最近10日
    # 至少8日 Close >= 舊頂
    # ========================================================

    recent_hold = (
        df.tail(
            hold_days
        )
        .copy()
    )

    hold_days_met = int(
        (
            recent_hold["close"]
            >= old_high
        ).sum()
    )

    if hold_days_met < hold_required_days:
        return None

    # ========================================================
    # 12. LIQUIDITY
    #
    # 最近10日平均成交額 > $20M
    # ========================================================

    recent_dv = (
        df.tail(
            dollar_volume_days
        )
        .copy()
    )

    recent_dv["dollar_volume"] = (
        recent_dv["close"]
        * recent_dv["volume"]
    )

    avg_dollar_volume = float(
        recent_dv["dollar_volume"]
        .mean()
    )

    if (
        avg_dollar_volume
        <= avg_dollar_volume_min
    ):
        return None

    # ========================================================
    # OUTPUT
    # ========================================================

    return {
        "symbol": symbol,

        "company":
            info.get("shortName")
            or info.get("longName")
            or symbol,

        "exchange":
            info.get("exchangeName")
            or info.get("fullExchangeName")
            or "",

        "market_cap":
            market_cap,

        "recent_close":
            round(recent_close, 2),

        "ma200":
            round(ma200, 2),

        "old_3y_high":
            round(old_high, 2),

        "old_3y_high_date":
            old_high_date,

        "dist_from_old_high_pct":
            round(distance_pct, 1),

        "first_breakout_date":
            first_breakout_date,

        "first_breakout_close":
            round(
                first_breakout_close,
                2
            ),

        "recent_window_peak_close":
            round(
                recent_window_peak_close,
                2
            ),

        "recent_window_peak_date":
            recent_window_peak_date,

        "recent_window_max_extension_pct":
            round(
                recent_window_extension_pct,
                1
            ),

        "consolidation_days":
            consolidation_days,

        "consolidation_high_close":
            round(
                consolidation_high_close,
                2
            ),

        "consolidation_low_close":
            round(
                consolidation_low_close,
                2
            ),

        "consolidation_range_pct":
            round(
                consolidation_range_pct,
                1
            ),

        "consolidation_avg_close":
            round(
                consolidation_avg_close,
                2
            ),

        "consolidation_avg_vs_old_high_pct":
            round(
                consolidation_avg_vs_old_high_pct,
                1
            ),

        "post_breakout_peak_close":
            round(
                post_breakout_peak_close,
                2
            ),

        "post_breakout_peak_date":
            post_breakout_peak_date,

        "max_extension_pct":
            round(
                max_extension_pct,
                1
            ),

        "pullback_from_peak_pct":
            round(
                pullback_from_peak_pct,
                1
            ),

        "hold_days_met":
            hold_days_met,

        "hold_days_total":
            hold_days,

        "avg_dollar_volume_10d":
            round(
                avg_dollar_volume,
                0
            ),

        "breakout_pct":
            round(
                distance_pct,
                1
            )
    }


# ============================================================
# BUILD ALL RESULTS
# ============================================================

def build_results():

    config = load_config()

    benchmark_symbol = (
        config["benchmark_symbol"]
    )

    symbols_df = fetch_us_symbols()

    symbols = (
        symbols_df["Symbol"]
        .tolist()
    )

    benchmark = get_benchmark_returns(
        benchmark_symbol
    )

    spy_5d = (
        benchmark[
            "five_day_return_pct"
        ]
    )

    spy_20d = (
        benchmark[
            "twenty_day_return_pct"
        ]
    )

    if (
        spy_5d is None
        or spy_20d is None
    ):
        raise ValueError(
            "Cannot calculate SPY returns"
        )

    batch_size = 80

    momentum_rows = []
    breakout_rows = []

    # ========================================================
    # PROCESS ALL SYMBOLS
    # ========================================================

    for i in range(
        0,
        len(symbols),
        batch_size
    ):

        batch = symbols[
            i:i + batch_size
        ]

        print(
            f"Processing "
            f"{i + 1}-"
            f"{min(i + batch_size, len(symbols))} "
            f"of {len(symbols)}"
        )

        try:

            history, summary = (
                get_price_history(
                    batch
                )
            )

        except Exception as e:

            print(
                f"Batch failed: {e}"
            )

            time.sleep(1)
            continue

        if not hasattr(
            history,
            "reset_index"
        ):
            continue

        try:
            history_df = (
                history.reset_index()
            )
        except Exception:
            continue

        if (
            history_df.empty
            or "date"
            not in history_df.columns
            or "symbol"
            not in history_df.columns
        ):
            continue

        history_df["date"] = (
            pd.to_datetime(
                history_df["date"],
                utc=True
            )
            .dt
            .tz_convert(None)
        )

        history_df = (
            history_df
            .sort_values(
                [
                    "symbol",
                    "date"
                ]
            )
        )

        # ====================================================
        # EACH STOCK
        # ====================================================

        for symbol in batch:

            try:

                info = summary.get(
                    symbol,
                    {}
                )

                if not isinstance(
                    info,
                    dict
                ):
                    continue

                stock_hist = (
                    history_df[
                        history_df["symbol"]
                        == symbol
                    ]
                    .copy()
                )

                if stock_hist.empty:
                    continue

                # MOMENTUM
                momentum_row = (
                    build_momentum_row(
                        symbol,
                        info,
                        stock_hist,
                        config,
                        spy_5d,
                        spy_20d
                    )
                )

                if momentum_row:
                    momentum_rows.append(
                        momentum_row
                    )

                # BREAKOUT / CONSOLIDATION
                breakout_row = (
                    build_breakout_row(
                        symbol,
                        info,
                        stock_hist,
                        config
                    )
                )

                if breakout_row:
                    breakout_rows.append(
                        breakout_row
                    )

            except Exception as e:

                print(
                    f"{symbol} error: {e}"
                )

                continue

    # ========================================================
    # SORT MOMENTUM
    # ========================================================

    momentum_rows = sorted(
        momentum_rows,
        key=lambda x:
            x["rs_20d_vs_spy_pct"],
        reverse=True
    )

    # ========================================================
    # SORT HIGH CONSOLIDATION
    #
    # 優先：
    #
    # 1. 20日波幅越細越好
    # 2. 越接近舊頂越好
    # 3. 守住舊頂日數越多越好
    #
    # 呢個排序比之前更加符合
    # 「高位整固」概念。
    # ========================================================

    breakout_rows = sorted(
        breakout_rows,
        key=lambda x: (
            x[
                "consolidation_range_pct"
            ],
            abs(
                x[
                    "dist_from_old_high_pct"
                ]
            ),
            -x[
                "hold_days_met"
            ]
        )
    )

    breakout_rules = (
        config[
            "breakout_setup"
        ]
    )

    # ========================================================
    # OUTPUT JSON
    # ========================================================

    output = {

        "generated_at":
            pd.Timestamp
            .now("UTC")
            .strftime(
                "%Y-%m-%d %H:%M UTC"
            ),

        "benchmark_symbol":
            benchmark_symbol,

        "rules": {

            "momentum": {

                **config["momentum"],

                "spy_five_day_return_pct":
                    round(spy_5d, 1),

                "spy_twenty_day_return_pct":
                    round(spy_20d, 1)
            },

            "breakout_setup": {

                **breakout_rules,

                "old_high_price_source":
                    "close"
            }
        },

        # 保留舊 key，
        # 避免前端因為改名而出問題
        "results":
            momentum_rows,

        "momentum_results":
            momentum_rows,

        "breakout_results":
            breakout_rows
    }

    with open(
        RESULTS_PATH,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"Momentum results: "
        f"{len(momentum_rows)}"
    )

    print(
        f"Breakout / consolidation results: "
        f"{len(breakout_rows)}"
    )

    print(
        f"Saved to: {RESULTS_PATH}"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    build_results()
