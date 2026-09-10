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
# DEBUG COUNTERS
# ============================================================

momentum_debug = {
    "checked": 0,
    "market_cap_pass": 0,
    "history_pass": 0,
    "returns_pass": 0,
    "rs_5d_pass": 0,
    "rs_20d_pass": 0,
    "high_52w_pass": 0,
    "final": 0
}

breakout_debug = {
    "checked": 0,
    "market_cap_pass": 0,
    "history_pass": 0,
    "ma200_pass": 0,
    "latest_distance_pass": 0,
    "breakout_pass": 0,
    "extension_pass": 0,
    "consolidation_range_pass": 0,
    "consolidation_avg_pass": 0,
    "pullback_pass": 0,
    "hold_pass": 0,
    "liquidity_pass": 0,
    "final": 0
}


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

    nasdaq_url = (
        "https://www.nasdaqtrader.com/dynamic/"
        "SymDir/nasdaqlisted.txt"
    )

    r = requests.get(
        nasdaq_url,
        timeout=30
    )

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

    other_url = (
        "https://www.nasdaqtrader.com/dynamic/"
        "SymDir/otherlisted.txt"
    )

    r = requests.get(
        other_url,
        timeout=30
    )

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
        "V": "IEX"
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

    df = df.dropna(
        subset=["Symbol"]
    )

    df = df[
        ~df["Symbol"]
        .astype(str)
        .str.contains(
            r"[\^\$]",
            regex=True
        )
    ]

    df = df[
        ~df["Symbol"]
        .astype(str)
        .str.contains(
            r"\.",
            regex=True
        )
    ]

    df = (
        df.drop_duplicates(
            subset=["Symbol"]
        )
        .reset_index(drop=True)
    )

    return df


# ============================================================
# HELPERS
# ============================================================

def safe_pct_return(
    current_price,
    past_price
):

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

    return float(
        temp.iloc[-1]
    )


# ============================================================
# PRICE HISTORY
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
# BENCHMARK
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

    if (
        hist is None
        or len(hist) == 0
    ):
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

    hist = hist.sort_values(
        "date"
    )

    closes = (
        hist
        .set_index("date")["close"]
        .dropna()
    )

    if closes.empty:
        raise ValueError(
            f"No close data for benchmark {symbol}"
        )

    latest_date = closes.index.max()

    latest_close = float(
        closes.iloc[-1]
    )

    price_5d = get_price_at_or_before(
        closes,
        latest_date - pd.Timedelta(days=7)
    )

    price_20d = get_price_at_or_before(
        closes,
        latest_date - pd.Timedelta(days=30)
    )

    return_5d = safe_pct_return(
        latest_close,
        price_5d
    )

    return_20d = safe_pct_return(
        latest_close,
        price_20d
    )

    if (
        return_5d is None
        or return_20d is None
    ):
        raise ValueError(
            f"Cannot calculate benchmark returns for {symbol}"
        )

    return {
        "latest_close": latest_close,
        "five_day_return_pct": return_5d,
        "twenty_day_return_pct": return_20d
    }


# ============================================================
# MOMENTUM
#
# 保持原本強勢股邏輯：
#
# Market Cap >= $10B
# 5D outperformance vs SPY >= 3%
# 20D outperformance vs SPY >= 8%
# 距離52W High <= 2%
# ============================================================

def build_momentum_row(
    symbol,
    info,
    stock_hist,
    config,
    spy_5d,
    spy_20d
):

    momentum_debug["checked"] += 1

    rules = config["momentum"]

    market_cap = info.get(
        "marketCap"
    )

    if (
        market_cap is None
        or market_cap
        < rules["market_cap_min"]
    ):
        return None

    momentum_debug[
        "market_cap_pass"
    ] += 1

    df = (
        stock_hist
        .sort_values("date")
        .copy()
    )

    required_columns = {
        "date",
        "close",
        "high"
    }

    if not required_columns.issubset(
        df.columns
    ):
        return None

    df = df.dropna(
        subset=[
            "close",
            "high"
        ]
    )

    if len(df) < 260:
        return None

    momentum_debug[
        "history_pass"
    ] += 1

    closes = (
        df
        .set_index("date")["close"]
        .dropna()
    )

    if closes.empty:
        return None

    latest_date = (
        closes.index.max()
    )

    recent_close = float(
        closes.iloc[-1]
    )

    price_5d = get_price_at_or_before(
        closes,
        latest_date
        - pd.Timedelta(days=7)
    )

    price_20d = get_price_at_or_before(
        closes,
        latest_date
        - pd.Timedelta(days=30)
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

    momentum_debug[
        "returns_pass"
    ] += 1

    rs_5d = (
        return_5d
        - spy_5d
    )

    rs_20d = (
        return_20d
        - spy_20d
    )

    if (
        rs_5d
        < rules[
            "rs_5d_vs_spy_min_pct"
        ]
    ):
        return None

    momentum_debug[
        "rs_5d_pass"
    ] += 1

    if (
        rs_20d
        < rules[
            "rs_20d_vs_spy_min_pct"
        ]
    ):
        return None

    momentum_debug[
        "rs_20d_pass"
    ] += 1

    trailing_52w = (
        df.tail(252)
    )

    if trailing_52w.empty:
        return None

    high_52w = float(
        trailing_52w[
            "high"
        ]
        .dropna()
        .max()
    )

    if (
        pd.isna(high_52w)
        or high_52w <= 0
    ):
        return None

    dist_from_52w_high_pct = (
        (
            recent_close
            / high_52w
        ) - 1
    ) * 100

    if (
        abs(
            dist_from_52w_high_pct
        )
        > rules[
            "max_dist_from_52w_high_pct"
        ]
    ):
        return None

    momentum_debug[
        "high_52w_pass"
    ] += 1

    momentum_debug[
        "final"
    ] += 1

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
            round(
                recent_close,
                2
            ),

        "five_day_return_pct":
            round(
                return_5d,
                1
            ),

        "twenty_day_return_pct":
            round(
                return_20d,
                1
            ),

        "spy_five_day_return_pct":
            round(
                spy_5d,
                1
            ),

        "spy_twenty_day_return_pct":
            round(
                spy_20d,
                1
            ),

        "rs_5d_vs_spy_pct":
            round(
                rs_5d,
                1
            ),

        "rs_20d_vs_spy_pct":
            round(
                rs_20d,
                1
            ),

        "high_52w":
            round(
                high_52w,
                2
            ),

        "dist_from_52w_high_pct":
            round(
                dist_from_52w_high_pct,
                1
            )
    }


# ============================================================
# BREAKOUT / HIGH BASE
# ============================================================

def build_breakout_row(
    symbol,
    info,
    stock_hist,
    config
):

    breakout_debug[
        "checked"
    ] += 1

    rules = config[
        "breakout_setup"
    ]

    # ========================================================
    # MARKET CAP
    # ========================================================

    market_cap = info.get(
        "marketCap"
    )

    if (
        market_cap is None
        or market_cap
        < rules["market_cap_min"]
    ):
        return None

    breakout_debug[
        "market_cap_pass"
    ] += 1

    required_columns = {
        "date",
        "close",
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
    # RULES
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
            10
        )
    )

    max_recent_extension_pct = float(
        rules.get(
            "recent_window_max_extension_pct",
            12
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
            12
        )
    )

    consolidation_avg_min_pct = float(
        rules.get(
            "consolidation_avg_close_min_pct",
            -1
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
            7
        )
    )

    max_pullback_pct = float(
        rules.get(
            "max_pullback_from_peak_pct",
            10
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

    breakout_debug[
        "history_pass"
    ] += 1

    recent_close = float(
        df.iloc[-1]["close"]
    )

    # ========================================================
    # MA200
    # ========================================================

    ma200 = float(
        df["close"]
        .tail(ma_days)
        .mean()
    )

    if recent_close <= ma200:
        return None

    breakout_debug[
        "ma200_pass"
    ] += 1

    # ========================================================
    # OLD HIGH
    #
    # 排除最近60個交易日後，
    # 歷史最高 Close
    # ========================================================

    if exclude_days > 0:

        old_window = (
            df.iloc[
                :-exclude_days
            ]
            .copy()
        )

    else:

        old_window = (
            df.copy()
        )

    old_window = (
        old_window
        .dropna(
            subset=["close"]
        )
    )

    if old_window.empty:
        return None

    old_high_idx = (
        old_window[
            "close"
        ]
        .idxmax()
    )

    old_high = float(
        old_window.loc[
            old_high_idx,
            "close"
        ]
    )

    if (
        pd.isna(old_high)
        or old_high <= 0
    ):
        return None

    old_high_date = (
        pd.Timestamp(
            old_window.loc[
                old_high_idx,
                "date"
            ]
        )
        .strftime(
            "%Y-%m-%d"
        )
    )

    # ========================================================
    # LATEST CLOSE
    #
    # 0% ～ +10%
    # ========================================================

    distance_pct = (
        (
            recent_close
            / old_high
        ) - 1
    ) * 100

    if (
        distance_pct
        < latest_close_min_pct
    ):
        return None

    if (
        distance_pct
        > latest_close_max_pct
    ):
        return None

    breakout_debug[
        "latest_distance_pass"
    ] += 1

    # ========================================================
    # 60-DAY BREAKOUT
    # ========================================================

    recent_window = (
        df.tail(
            breakout_window_days
        )
        .copy()
    )

    breakout_rows = (
        recent_window[
            recent_window[
                "close"
            ] > old_high
        ]
        .copy()
    )

    if breakout_rows.empty:
        return None

    breakout_debug[
        "breakout_pass"
    ] += 1

    first_breakout = (
        breakout_rows.iloc[0]
    )

    first_breakout_date_ts = (
        pd.Timestamp(
            first_breakout[
                "date"
            ]
        )
    )

    first_breakout_date = (
        first_breakout_date_ts
        .strftime(
            "%Y-%m-%d"
        )
    )

    first_breakout_close = float(
        first_breakout[
            "close"
        ]
    )

    # ========================================================
    # RECENT 60-DAY EXTENSION
    #
    # 最高 Close <= 舊頂 +12%
    # ========================================================

    recent_peak_close = float(
        recent_window[
            "close"
        ].max()
    )

    recent_peak_idx = (
        recent_window[
            "close"
        ].idxmax()
    )

    recent_peak_date = (
        pd.Timestamp(
            recent_window.loc[
                recent_peak_idx,
                "date"
            ]
        )
        .strftime(
            "%Y-%m-%d"
        )
    )

    recent_extension_pct = (
        (
            recent_peak_close
            / old_high
        ) - 1
    ) * 100

    if (
        recent_extension_pct
        > max_recent_extension_pct
    ):
        return None

    breakout_debug[
        "extension_pass"
    ] += 1

    # ========================================================
    # 20-DAY CONSOLIDATION RANGE
    #
    # 最近20日：
    #
    # (最高Close - 最低Close)
    # / 最低Close
    #
    # <= 12%
    # ========================================================

    consolidation = (
        df.tail(
            consolidation_days
        )
        .copy()
    )

    if (
        len(consolidation)
        < consolidation_days
    ):
        return None

    consolidation_high = float(
        consolidation[
            "close"
        ].max()
    )

    consolidation_low = float(
        consolidation[
            "close"
        ].min()
    )

    consolidation_avg = float(
        consolidation[
            "close"
        ].mean()
    )

    if consolidation_low <= 0:
        return None

    consolidation_range_pct = (
        (
            consolidation_high
            - consolidation_low
        )
        / consolidation_low
    ) * 100

    if (
        consolidation_range_pct
        > consolidation_range_max_pct
    ):
        return None

    breakout_debug[
        "consolidation_range_pass"
    ] += 1

    # ========================================================
    # 20-DAY AVERAGE CLOSE
    #
    # 平均 Close 最多可以比舊頂低1%
    # ========================================================

    consolidation_avg_vs_old_high_pct = (
        (
            consolidation_avg
            / old_high
        ) - 1
    ) * 100

    if (
        consolidation_avg_vs_old_high_pct
        < consolidation_avg_min_pct
    ):
        return None

    breakout_debug[
        "consolidation_avg_pass"
    ] += 1

    # ========================================================
    # POST BREAKOUT PEAK
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

    post_peak_close = float(
        post_breakout[
            "close"
        ].max()
    )

    post_peak_idx = (
        post_breakout[
            "close"
        ].idxmax()
    )

    post_peak_date = (
        pd.Timestamp(
            post_breakout.loc[
                post_peak_idx,
                "date"
            ]
        )
        .strftime(
            "%Y-%m-%d"
        )
    )

    max_extension_pct = (
        (
            post_peak_close
            / old_high
        ) - 1
    ) * 100

    # ========================================================
    # PULLBACK
    #
    # 由突破後最高Close回撤 <= 10%
    # ========================================================

    pullback_pct = (
        (
            recent_close
            / post_peak_close
        ) - 1
    ) * 100

    if (
        pullback_pct
        < -max_pullback_pct
    ):
        return None

    breakout_debug[
        "pullback_pass"
    ] += 1

    # ========================================================
    # HOLD
    #
    # 最近10日最少7日 >= 舊頂
    # ========================================================

    recent_hold = (
        df.tail(
            hold_days
        )
        .copy()
    )

    hold_days_met = int(
        (
            recent_hold[
                "close"
            ] >= old_high
        ).sum()
    )

    if (
        hold_days_met
        < hold_required_days
    ):
        return None

    breakout_debug[
        "hold_pass"
    ] += 1

    # ========================================================
    # LIQUIDITY
    # ========================================================

    recent_dv = (
        df.tail(
            dollar_volume_days
        )
        .copy()
    )

    recent_dv[
        "dollar_volume"
    ] = (
        recent_dv[
            "close"
        ]
        * recent_dv[
            "volume"
        ]
    )

    avg_dollar_volume = float(
        recent_dv[
            "dollar_volume"
        ].mean()
    )

    if (
        avg_dollar_volume
        <= avg_dollar_volume_min
    ):
        return None

    breakout_debug[
        "liquidity_pass"
    ] += 1

    breakout_debug[
        "final"
    ] += 1

    # ========================================================
    # OUTPUT
    # ========================================================

    return {
        "symbol":
            symbol,

        "company":
            info.get("shortName")
            or info.get("longName")
            or symbol,

        "exchange":
            info.get("exchangeName")
            or info.get(
                "fullExchangeName"
            )
            or "",

        "market_cap":
            market_cap,

        "recent_close":
            round(
                recent_close,
                2
            ),

        "ma200":
            round(
                ma200,
                2
            ),

        "old_3y_high":
            round(
                old_high,
                2
            ),

        "old_3y_high_date":
            old_high_date,

        "dist_from_old_high_pct":
            round(
                distance_pct,
                1
            ),

        "first_breakout_date":
            first_breakout_date,

        "first_breakout_close":
            round(
                first_breakout_close,
                2
            ),

        "recent_window_peak_close":
            round(
                recent_peak_close,
                2
            ),

        "recent_window_peak_date":
            recent_peak_date,

        "recent_window_max_extension_pct":
            round(
                recent_extension_pct,
                1
            ),

        "consolidation_days":
            consolidation_days,

        "consolidation_high_close":
            round(
                consolidation_high,
                2
            ),

        "consolidation_low_close":
            round(
                consolidation_low,
                2
            ),

        "consolidation_range_pct":
            round(
                consolidation_range_pct,
                1
            ),

        "consolidation_avg_close":
            round(
                consolidation_avg,
                2
            ),

        "consolidation_avg_vs_old_high_pct":
            round(
                consolidation_avg_vs_old_high_pct,
                1
            ),

        "post_breakout_peak_close":
            round(
                post_peak_close,
                2
            ),

        "post_breakout_peak_date":
            post_peak_date,

        "max_extension_pct":
            round(
                max_extension_pct,
                1
            ),

        "pullback_from_peak_pct":
            round(
                pullback_pct,
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
# PRINT DEBUG
# ============================================================

def print_debug_report():

    print("\n")
    print("=" * 60)
    print("SCREENING DEBUG REPORT")
    print("=" * 60)

    print("\nMOMENTUM / 強勢股")
    print("-" * 60)

    print(
        f"Stocks checked:          "
        f"{momentum_debug['checked']}"
    )

    print(
        f"Market cap passed:       "
        f"{momentum_debug['market_cap_pass']}"
    )

    print(
        f"History passed:          "
        f"{momentum_debug['history_pass']}"
    )

    print(
        f"Returns calculated:      "
        f"{momentum_debug['returns_pass']}"
    )

    print(
        f"5D RS passed:            "
        f"{momentum_debug['rs_5d_pass']}"
    )

    print(
        f"20D RS passed:           "
        f"{momentum_debug['rs_20d_pass']}"
    )

    print(
        f"52W high passed:         "
        f"{momentum_debug['high_52w_pass']}"
    )

    print(
        f"FINAL MOMENTUM:          "
        f"{momentum_debug['final']}"
    )

    print("\n")
    print("BREAKOUT / 高位整固")
    print("-" * 60)

    print(
        f"Stocks checked:          "
        f"{breakout_debug['checked']}"
    )

    print(
        f"Market cap passed:       "
        f"{breakout_debug['market_cap_pass']}"
    )

    print(
        f"History passed:          "
        f"{breakout_debug['history_pass']}"
    )

    print(
        f"Above MA200:             "
        f"{breakout_debug['ma200_pass']}"
    )

    print(
        f"Near old high:           "
        f"{breakout_debug['latest_distance_pass']}"
    )

    print(
        f"60D breakout:            "
        f"{breakout_debug['breakout_pass']}"
    )

    print(
        f"60D extension passed:    "
        f"{breakout_debug['extension_pass']}"
    )

    print(
        f"20D range passed:        "
        f"{breakout_debug['consolidation_range_pass']}"
    )

    print(
        f"20D average passed:      "
        f"{breakout_debug['consolidation_avg_pass']}"
    )

    print(
        f"Pullback passed:         "
        f"{breakout_debug['pullback_pass']}"
    )

    print(
        f"Hold passed:             "
        f"{breakout_debug['hold_pass']}"
    )

    print(
        f"Liquidity passed:        "
        f"{breakout_debug['liquidity_pass']}"
    )

    print(
        f"FINAL BREAKOUT:          "
        f"{breakout_debug['final']}"
    )

    print("=" * 60)
    print("\n")


# ============================================================
# BUILD RESULTS
# ============================================================

def build_results():

    config = load_config()

    benchmark_symbol = (
        config["benchmark_symbol"]
    )

    print(
        f"Loading {benchmark_symbol} benchmark..."
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

    print(
        f"SPY 5D return: "
        f"{spy_5d:.2f}%"
    )

    print(
        f"SPY 20D return: "
        f"{spy_20d:.2f}%"
    )

    print(
        "\nLoading US stock symbols..."
    )

    symbols_df = (
        fetch_us_symbols()
    )

    symbols = (
        symbols_df[
            "Symbol"
        ].tolist()
    )

    print(
        f"Total symbols: "
        f"{len(symbols)}"
    )

    batch_size = 80

    momentum_rows = []
    breakout_rows = []

    failed_batches = 0
    failed_symbols = 0

    # ========================================================
    # PROCESS BATCHES
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
            f"\nProcessing "
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

            failed_batches += 1

            print(
                f"ERROR downloading batch: "
                f"{e}"
            )

            time.sleep(1)

            continue

        if not hasattr(
            history,
            "reset_index"
        ):

            failed_batches += 1

            print(
                "ERROR: history has no reset_index"
            )

            continue

        try:

            history_df = (
                history.reset_index()
            )

        except Exception as e:

            failed_batches += 1

            print(
                f"ERROR converting history: "
                f"{e}"
            )

            continue

        if history_df.empty:

            failed_batches += 1

            print(
                "ERROR: empty history dataframe"
            )

            continue

        if (
            "date"
            not in history_df.columns
            or "symbol"
            not in history_df.columns
        ):

            failed_batches += 1

            print(
                "ERROR: history missing date/symbol columns"
            )

            continue

        try:

            history_df[
                "date"
            ] = (
                pd.to_datetime(
                    history_df[
                        "date"
                    ],
                    utc=True
                )
                .dt
                .tz_convert(None)
            )

        except Exception as e:

            failed_batches += 1

            print(
                f"ERROR converting dates: "
                f"{e}"
            )

            continue

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
        # EACH SYMBOL
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

                    failed_symbols += 1

                    print(
                        f"{symbol}: "
                        f"invalid price info"
                    )

                    continue

                stock_hist = (
                    history_df[
                        history_df[
                            "symbol"
                        ] == symbol
                    ]
                    .copy()
                )

                if stock_hist.empty:

                    failed_symbols += 1

                    continue

                # ============================================
                # MOMENTUM
                # ============================================

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

                # ============================================
                # BREAKOUT
                # ============================================

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

                failed_symbols += 1

                print(
                    f"{symbol} ERROR: "
                    f"{type(e).__name__}: "
                    f"{e}"
                )

                continue

    # ========================================================
    # SORT MOMENTUM
    # ========================================================

    momentum_rows = sorted(
        momentum_rows,
        key=lambda x:
            x[
                "rs_20d_vs_spy_pct"
            ],
        reverse=True
    )

    # ========================================================
    # SORT BREAKOUT
    #
    # 20D range 越細排越前
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

    # ========================================================
    # RESULTS
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
                **config[
                    "momentum"
                ],

                "spy_five_day_return_pct":
                    round(
                        spy_5d,
                        1
                    ),

                "spy_twenty_day_return_pct":
                    round(
                        spy_20d,
                        1
                    )
            },

            "breakout_setup": {
                **config[
                    "breakout_setup"
                ],

                "old_high_price_source":
                    "close"
            }
        },

        # 舊 frontend compatibility
        "results":
            momentum_rows,

        "momentum_results":
            momentum_rows,

        "breakout_results":
            breakout_rows,

        # Debug data 亦寫入 JSON
        "debug": {

            "momentum":
                momentum_debug,

            "breakout":
                breakout_debug,

            "failed_batches":
                failed_batches,

            "failed_symbols":
                failed_symbols
        }
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

    # ========================================================
    # DEBUG REPORT
    # ========================================================

    print_debug_report()

    print(
        f"Failed batches: "
        f"{failed_batches}"
    )

    print(
        f"Failed symbols: "
        f"{failed_symbols}"
    )

    print(
        f"\nMomentum results: "
        f"{len(momentum_rows)}"
    )

    print(
        f"Breakout results: "
        f"{len(breakout_rows)}"
    )

    print(
        f"\nSaved to: "
        f"{RESULTS_PATH}"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    build_results()
