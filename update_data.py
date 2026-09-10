def build_breakout_row(
    symbol,
    info,
    stock_hist,
    config
):
    rules = config["breakout_setup"]

    # ========================================================
    # 1. Market Cap
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

    if not required_columns.issubset(stock_hist.columns):
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

    # 移除異常價格
    df = df[
        (df["close"] > 0)
        & (df["volume"] >= 0)
    ].copy()

    if df.empty:
        return None

    # ========================================================
    # 固定使用最近 60 個交易日
    # ========================================================

    exclude_days = 60
    breakout_window_days = 60

    ma_days = int(
        rules["ma_days"]
    )

    hold_days = int(
        rules["hold_days"]
    )

    hold_required_days = int(
        rules["hold_required_days"]
    )

    dollar_volume_days = int(
        rules["avg_dollar_volume_days"]
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

    latest = df.iloc[-1]

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
    # 過去約 3 年最高「收市價」
    # 但排除最近 60 個交易日
    # ========================================================

    old_window = (
        df.iloc[:-exclude_days]
        .copy()
    )

    if old_window.empty:
        return None

    old_window = old_window.dropna(
        subset=["close"]
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
    # 最新 Close：
    # 必須 >= 舊頂
    # 必須 <= 舊頂 +15%
    # ========================================================

    distance_pct = (
        (
            recent_close
            / old_high
        ) - 1
    ) * 100

    if distance_pct < 0:
        return None

    if (
        distance_pct
        >
        BREAKOUT_MAX_DISTANCE_FROM_OLD_HIGH_PCT
    ):
        return None

    # ========================================================
    # 5. 最近 60 日 Breakout
    #
    # 最近 60 個交易日至少有一日：
    # Close > 舊頂
    # ========================================================

    recent_60 = (
        df.tail(60)
        .copy()
    )

    breakout_closes = (
        recent_60[
            recent_60["close"] > old_high
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
            first_breakout_row["date"]
        )
    )

    first_breakout_date = (
        first_breakout_date_ts
        .strftime("%Y-%m-%d")
    )

    breakout_close = float(
        first_breakout_row["close"]
    )

    # ========================================================
    # 6. 最近 60 日最高收市價
    #
    # 新規則：
    #
    # 最近60日任何一日最高 Close
    # 都唔可以高過舊頂 15%
    #
    # 舊頂 $100：
    #
    # 最近60日最高 $114 -> PASS
    # 最近60日最高 $115 -> PASS
    # 最近60日最高 $116 -> FAIL
    # ========================================================

    recent_60_peak_close = float(
        recent_60["close"].max()
    )

    recent_60_peak_idx = (
        recent_60["close"]
        .idxmax()
    )

    recent_60_peak_date = (
        pd.Timestamp(
            recent_60.loc[
                recent_60_peak_idx,
                "date"
            ]
        )
        .strftime("%Y-%m-%d")
    )

    recent_60_max_extension_pct = (
        (
            recent_60_peak_close
            / old_high
        ) - 1
    ) * 100

    if (
        recent_60_max_extension_pct
        >
        BREAKOUT_MAX_EXTENSION_PCT
    ):
        return None

    # ========================================================
    # 7. 突破後最高收市及回撤
    #
    # 保留原本規則：
    # 最新收市相對突破後最高收市
    # 回撤唔可以超過 10%
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
    # 8. Hold Above Old High
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
    # 9. Liquidity
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

    # ========================================================
    # Output
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
            or info.get("fullExchangeName")
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
                breakout_close,
                2
            ),

        # 最近60日最高收市
        "recent_60d_peak_close":
            round(
                recent_60_peak_close,
                2
            ),

        "recent_60d_peak_date":
            recent_60_peak_date,

        "recent_60d_max_extension_pct":
            round(
                recent_60_max_extension_pct,
                1
            ),

        # 突破後最高收市
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
                breakout_pct,
                1
            ),
    }
