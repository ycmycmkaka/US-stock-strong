import json
import time
from pathlib import Path

import pandas as pd
import requests
from yahooquery import Ticker


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
RESULTS_PATH = BASE_DIR / "results.json"


# ============================================================
# Breakout 策略額外規則
# ============================================================

# 突破後如果曾經升高，
# 最新收市相對突破後最高收市回撤超過 10%，淘汰
BREAKOUT_MAX_PULLBACK_FROM_PEAK_PCT = 10.0


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_us_symbols():
    url1 = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"

    r1 = requests.get(
        url1,
        timeout=30
    )

    r1.raise_for_status()

    df1 = pd.read_csv(
        pd.io.common.StringIO(r1.text),
        sep="|"
    )

    df1 = df1[
        df1["Symbol"] != "File Creation Time"
    ]

    df1 = df1[["Symbol"]].copy()

    df1["exchange"] = "NASDAQ"

    url2 = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

    r2 = requests.get(
        url2,
        timeout=30
    )

    r2.raise_for_status()

    df2 = pd.read_csv(
        pd.io.common.StringIO(r2.text),
        sep="|"
    )

    df2 = df2[
        df2["ACT Symbol"] != "File Creation Time"
    ]

    df2 = df2.rename(
        columns={
            "ACT Symbol": "Symbol",
            "Exchange": "exchange"
        }
    )

    df2 = df2[
        ["Symbol", "exchange"]
    ].copy()

    exchange_map = {
        "N": "NYSE",
        "A": "AMEX",
        "P": "NYSE Arca",
        "Z": "BATS",
        "V": "IEX",
    }

    df2["exchange"] = (
        df2["exchange"]
        .map(exchange_map)
        .fillna(df2["exchange"])
    )

    df = pd.concat(
        [df1, df2],
        ignore_index=True
    )

    df = df.dropna()

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
        df.drop_duplicates(
            subset=["Symbol"]
        )
        .reset_index(drop=True)
    )

    return df


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
        current_price / past_price - 1
    ) * 100


def get_price_at_or_before(
    series: pd.Series,
    target_date: pd.Timestamp
):
    if series.empty:
        return None

    s = series[
        series.index <= target_date
    ]

    if s.empty:
        return None

    return float(
        s.iloc[-1]
    )


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


def get_benchmark_returns(
    symbol: str
):
    t = Ticker(
        symbol,
        asynchronous=False
    )

    hist = t.history(
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

    latest_date = (
        closes.index.max()
    )

    latest_close = float(
        closes.iloc[-1]
    )

    five_days_ago = (
        latest_date
        - pd.Timedelta(days=7)
    )

    twenty_days_ago = (
        latest_date
        - pd.Timedelta(days=30)
    )

    price_5d = (
        get_price_at_or_before(
            closes,
            five_days_ago
        )
    )

    price_20d = (
        get_price_at_or_before(
            closes,
            twenty_days_ago
        )
    )

    return {
        "latest_close":
            latest_close,

        "five_day_return_pct":
            safe_pct_return(
                latest_close,
                price_5d
            ),

        "twenty_day_return_pct":
            safe_pct_return(
                latest_close,
                price_20d
            ),
    }


# ============================================================
# Momentum 篩選
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

    market_cap = info.get(
        "marketCap"
    )

    if (
        market_cap is None
        or market_cap
        < rules["market_cap_min"]
    ):
        return None

    stock_hist = (
        stock_hist
        .sort_values("date")
        .copy()
    )

    closes = (
        stock_hist
        .set_index("date")["close"]
        .dropna()
    )

    if len(closes) < 260:
        return None

    latest_date = (
        closes.index.max()
    )

    recent_close = float(
        closes.iloc[-1]
    )

    price_5d = (
        get_price_at_or_before(
            closes,
            latest_date
            - pd.Timedelta(days=7)
        )
    )

    price_20d = (
        get_price_at_or_before(
            closes,
            latest_date
            - pd.Timedelta(days=30)
        )
    )

    return_5d = (
        safe_pct_return(
            recent_close,
            price_5d
        )
    )

    return_20d = (
        safe_pct_return(
            recent_close,
            price_20d
        )
    )

    if (
        return_5d is None
        or return_20d is None
    ):
        return None

    rs_5d = (
        return_5d - spy_5d
    )

    rs_20d = (
        return_20d - spy_20d
    )

    trailing_52w = (
        stock_hist.tail(252)
    )

    if trailing_52w.empty:
        return None

    high_52w = float(
        trailing_52w["high"]
        .dropna()
        .max()
    )

    if (
        not high_52w
        or pd.isna(high_52w)
    ):
        return None

    dist_from_52w_high_pct = (
        (
            recent_close / high_52w
        ) - 1
    ) * 100

    if (
        rs_5d
        < rules[
            "rs_5d_vs_spy_min_pct"
        ]
    ):
        return None

    if (
        rs_20d
        < rules[
            "rs_20d_vs_spy_min_pct"
        ]
    ):
        return None

    if (
        abs(
            dist_from_52w_high_pct
        )
        > rules[
            "max_dist_from_52w_high_pct"
        ]
    ):
        return None

    return {
        "symbol":
            symbol,

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
            ),
    }


# ============================================================
# Breakout Setup
# ============================================================

def build_breakout_row(
    symbol,
    info,
    stock_hist,
    config
):
    rules = config[
        "breakout_setup"
    ]

    # --------------------------------------------------------
    # 1. Market Cap
    # --------------------------------------------------------

    market_cap = info.get(
        "marketCap"
    )

    if (
        market_cap is None
        or market_cap
        < rules["market_cap_min"]
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

    if df.empty:
        return None

    # 移除任何異常 0 / 負數價格
    df = df[
        (df["close"] > 0)
        & (df["volume"] >= 0)
    ].copy()

    if df.empty:
        return None

    # ========================================================
    # 從 config.json 讀取 Breakout 條件
    # ========================================================

    exclude_days = int(
        rules[
            "exclude_recent_trading_days"
        ]
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
            15
        )
    )

    max_recent_extension_allowed_pct = float(
        rules.get(
            "recent_window_max_extension_pct",
            15
        )
    )

    ma_days = int(
        rules["ma_days"]
    )

    hold_days = int(
        rules["hold_days"]
    )

    hold_required_days = int(
        rules[
            "hold_required_days"
        ]
    )

    dollar_volume_days = int(
        rules[
            "avg_dollar_volume_days"
        ]
    )

    min_history = max(
        ma_days,
        exclude_days + 60,
        breakout_window_days,
        hold_days,
        dollar_volume_days,
    )

    if len(df) < min_history:
        return None

    latest = (
        df.iloc[-1]
    )

    recent_close = float(
        latest["close"]
    )

    # ========================================================
    # 2. MA200 Trend Filter
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
    # 舊頂：
    # 過去約3年最高收市價 Close
    # 但排除最近 N 個交易日
    #
    # 而家 config 設為 60，
    # 即排除最近60個交易日。
    # ========================================================

    if exclude_days > 0:
        old_window = (
            df.iloc[:-exclude_days]
            .copy()
        )
    else:
        old_window = (
            df.copy()
        )

    if old_window.empty:
        return None

    old_window = (
        old_window
        .dropna(
            subset=["close"]
        )
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
        old_high <= 0
        or pd.isna(old_high)
    ):
        return None

    # ========================================================
    # 4. 最新收市價距離舊頂
    #
    # 按 config：
    #
    # latest_close_min_pct = 0
    # latest_close_max_pct = 15
    #
    # 即最新 Close 必須：
    #
    # >= 舊頂
    # <= 舊頂 +15%
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

    # ========================================================
    # 5. Confirmed Breakout
    #
    # 最近60個交易日至少有一日：
    #
    # Close > 舊頂
    #
    # breakout_window_days 由 config 控制
    # ========================================================

    recent_breakout_window = (
        df.tail(
            breakout_window_days
        )
        .copy()
    )

    breakout_closes = (
        recent_breakout_window[
            recent_breakout_window[
                "close"
            ] > old_high
        ]
        .copy()
    )

    if breakout_closes.empty:
        return None

    first_breakout_row = (
        breakout_closes.iloc[0]
    )

    first_breakout_date_ts = (
        pd.Timestamp(
            first_breakout_row[
                "date"
            ]
        )
    )

    first_breakout_date = (
        first_breakout_date_ts
        .strftime("%Y-%m-%d")
    )

    breakout_close = float(
        first_breakout_row[
            "close"
        ]
    )

    # ========================================================
    # 6. 最近60日最高收市價不能高過舊頂15%
    #
    # 新規則：
    #
    # 舊頂 = $100
    #
    # 最近60日最高 Close：
    #
    # $114 = +14% -> PASS
    # $115 = +15% -> PASS
    # $116 = +16% -> FAIL
    #
    # 即使今日跌返 $105，
    # 只要最近60日曾經收市高過舊頂15%，
    # 都會被排除。
    # ========================================================

    recent_window_peak_close = float(
        recent_breakout_window[
            "close"
        ].max()
    )

    recent_window_peak_idx = (
        recent_breakout_window[
            "close"
        ].idxmax()
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

    recent_window_max_extension_pct = (
        (
            recent_window_peak_close
            / old_high
        ) - 1
    ) * 100

    if (
        recent_window_max_extension_pct
        > max_recent_extension_allowed_pct
    ):
        return None

    # ========================================================
    # 7. 第一次突破後最高收市價
    #
    # 保留原本資料，
    # 用作計算今日由突破後高位回撤幾多。
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

    post_breakout_max_extension_pct = (
        (
            post_breakout_peak_close
            / old_high
        ) - 1
    ) * 100

    # ========================================================
    # 8. 突破後由高位回撤幅度
    #
    # 最新收市價相對突破後最高收市價，
    # 回撤不能超過10%。
    # ========================================================

    pullback_from_peak_pct = (
        (
            recent_close
            / post_breakout_peak_close
        ) - 1
    ) * 100

    if (
        pullback_from_peak_pct
        <
        -BREAKOUT_MAX_PULLBACK_FROM_PEAK_PCT
    ):
        return None

    # ========================================================
    # 9. Hold Above Old High
    #
    # 最近10日，
    # 至少8日收市 >= 舊頂
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

    if (
        hold_days_met
        < hold_required_days
    ):
        return None

    # ========================================================
    # 10. Liquidity
    #
    # 最近 N 日平均成交額
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
        recent_dv["close"]
        * recent_dv["volume"]
    )

    avg_dollar_volume = float(
        recent_dv[
            "dollar_volume"
        ].mean()
    )

    if (
        avg_dollar_volume
        <= float(
            rules[
                "avg_dollar_volume_min"
            ]
        )
    ):
        return None

    breakout_pct = (
        (
            recent_close
            / old_high
        ) - 1
    ) * 100

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

        # --------------------------------
        # 舊頂 = 歷史最高 Close
        # 排除最近60個交易日
        # --------------------------------

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

        # --------------------------------
        # Breakout
        # --------------------------------

        "first_breakout_date":
            first_breakout_date,

        "first_breakout_close":
            round(
                breakout_close,
                2
            ),

        # --------------------------------
        # 最近60日最高收市價
        # --------------------------------

        "recent_window_peak_close":
            round(
                recent_window_peak_close,
                2
            ),

        "recent_window_peak_date":
            recent_window_peak_date,

        "recent_window_max_extension_pct":
            round(
                recent_window_max_extension_pct,
                1
            ),

        # --------------------------------
        # 第一次突破後最高收市價
        # --------------------------------

        "post_breakout_peak_close":
            round(
                post_breakout_peak_close,
                2
            ),

        "post_breakout_peak_date":
            post_breakout_peak_date,

        "max_extension_pct":
            round(
                post_breakout_max_extension_pct,
                1
            ),

        "pullback_from_peak_pct":
            round(
                pullback_from_peak_pct,
                1
            ),

        # --------------------------------
        # Hold
        # --------------------------------

        "hold_days_met":
            hold_days_met,

        "hold_days_total":
            hold_days,

        # --------------------------------
        # Liquidity
        # --------------------------------

        "avg_dollar_volume_10d":
            round(
                avg_dollar_volume,
                0
            ),

        "breakout_pct":
            round(
                breakout_pct,
                1
            ),
    }


# ============================================================
# Build Results
# ============================================================

def build_results():
    config = load_config()

    benchmark_symbol = (
        config[
            "benchmark_symbol"
        ]
    )

    symbols_df = (
        fetch_us_symbols()
    )

    symbols = (
        symbols_df["Symbol"]
        .tolist()
    )

    benchmark = (
        get_benchmark_returns(
            benchmark_symbol
        )
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

    batch_size = 80

    momentum_rows = []
    breakout_rows = []

    for i in range(
        0,
        len(symbols),
        batch_size
    ):
        batch = symbols[
            i:i + batch_size
        ]

        try:
            history, summary = (
                get_price_history(
                    batch
                )
            )

        except Exception:
            time.sleep(1)
            continue

        if hasattr(
            history,
            "reset_index"
        ):
            history_df = (
                history.reset_index()
            )
        else:
            history_df = (
                pd.DataFrame()
            )

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
                        history_df[
                            "symbol"
                        ] == symbol
                    ]
                    .copy()
                )

                if stock_hist.empty:
                    continue

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

            except Exception:
                continue

    momentum_rows = sorted(
        momentum_rows,
        key=lambda x:
            x[
                "rs_20d_vs_spy_pct"
            ],
        reverse=True
    )

    # --------------------------------------------------------
    # Breakout 排序
    #
    # 優先：
    # 1. 越接近舊頂
    # 2. 守住舊頂日數越多
    # 3. 流動性越高
    # --------------------------------------------------------

    breakout_rows = sorted(
        breakout_rows,
        key=lambda x: (
            -abs(
                x[
                    "dist_from_old_high_pct"
                ]
            ),
            x[
                "hold_days_met"
            ],
            x[
                "avg_dollar_volume_10d"
            ],
        ),
        reverse=True
    )

    breakout_rules = (
        config[
            "breakout_setup"
        ]
    )

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
                    ),
            },

            "breakout_setup": {
                **breakout_rules,

                # 寫入 results.json
                # 方便前端顯示實際規則

                "old_high_price_source":
                    "close",

                "latest_close_min_pct":
                    float(
                        breakout_rules.get(
                            "latest_close_min_pct",
                            0
                        )
                    ),

                "latest_close_max_pct":
                    float(
                        breakout_rules.get(
                            "latest_close_max_pct",
                            15
                        )
                    ),

                "recent_window_max_extension_pct":
                    float(
                        breakout_rules.get(
                            "recent_window_max_extension_pct",
                            15
                        )
                    ),

                "max_pullback_from_peak_pct":
                    BREAKOUT_MAX_PULLBACK_FROM_PEAK_PCT,
            },
        },

        "results":
            momentum_rows,

        "momentum_results":
            momentum_rows,

        "breakout_results":
            breakout_rows,
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


if __name__ == "__main__":
    build_results()
