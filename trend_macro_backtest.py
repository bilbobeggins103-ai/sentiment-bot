"""
Trend Filter + RSI/MA Entry + Makro-filtr po stavke FRS
==========================================================
Testiruem na periode 2022-2024, gde stavka realno menyalas (hikes/cuts),
v otlichie ot poslednih 90 dnej 2026 goda, gde vsyo vremya byl "hold".

Ideya makro-filtra: ne otkryvat novye longi v techenie MACRO_BLOCK_DAYS dnej
posle POVYSHENIYA stavki FRS - v eti nedeli ETH istoricheski chasche padaet
(my eto videli v otdelnom analize: v srednem -5.84% za 7 dnej posle hike).

Sravnivaem strategiyu BEZ makro-filtra i S makro-filtrom na odnom i tom zhe
periode, chtoby chestno uvidet, pomogaet li on.

Trebovaniya: pip install pandas numpy requests
Zapusk:     python trend_macro_backtest.py
"""

import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

SYMBOL = "ETHUSDT"
TREND_TF = "4h"
ENTRY_TF = "1h"
START_DATE = "2022-01-01"
END_DATE = "2025-01-15"

TREND_FAST, TREND_SLOW = 50, 200
ENTRY_FAST, ENTRY_SLOW = 9, 21
RSI_PERIOD = 14
RSI_LOW, RSI_HIGH = 40, 70
STOP_LOSS_PCT = 0.015
TAKE_PROFIT_PCT = 0.03
FEE_PCT = 0.001

MACRO_BLOCK_DAYS = 7   # posle povysheniya stavki blokiruem novye vhody na stolko dnej

FOMC_HISTORY = [
    ("2022-01-26", "hold"), ("2022-03-16", "hike"), ("2022-05-04", "hike"),
    ("2022-06-15", "hike"), ("2022-07-27", "hike"), ("2022-09-21", "hike"),
    ("2022-11-02", "hike"), ("2022-12-14", "hike"), ("2023-02-01", "hike"),
    ("2023-03-22", "hike"), ("2023-05-03", "hike"), ("2023-06-14", "hold"),
    ("2023-07-26", "hike"), ("2023-09-20", "hold"), ("2023-11-01", "hold"),
    ("2023-12-13", "hold"), ("2024-01-31", "hold"), ("2024-03-20", "hold"),
    ("2024-05-01", "hold"), ("2024-06-12", "hold"), ("2024-07-31", "hold"),
    ("2024-09-18", "cut"), ("2024-11-07", "cut"), ("2024-12-18", "cut"),
]


def build_hike_block_windows():
    """Stroim spisok intervalov (start, end), kogda novye vhody zablokirovany."""
    windows = []
    for date_str, decision in FOMC_HISTORY:
        if decision == "hike":
            start = pd.Timestamp(date_str)
            end = start + timedelta(days=MACRO_BLOCK_DAYS)
            windows.append((start, end))
    return windows


def is_blocked(ts, windows):
    for start, end in windows:
        if start <= ts <= end:
            return True
    return False


def fetch_klines(symbol, interval, start_ms, end_ms):
    all_rows = []
    cur = start_ms
    while cur < end_ms:
        params = {
            "symbol": symbol, "interval": interval,
            "startTime": cur, "endTime": end_ms, "limit": 1000,
        }
        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=15)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        all_rows.extend(rows)
        cur = rows[-1][0] + 1
        if len(rows) < 1000:
            break
        time.sleep(0.2)

    df = pd.DataFrame(all_rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore"
    ])
    df["close"] = df["close"].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_localize(None)
    df.set_index("open_time", inplace=True)
    return df[["close"]]


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def prepare_trend(df):
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=TREND_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=TREND_SLOW, adjust=False).mean()
    df["uptrend"] = df["ema_fast"] > df["ema_slow"]
    return df


def prepare_entry(df):
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=ENTRY_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=ENTRY_SLOW, adjust=False).mean()
    df["rsi"] = rsi(df["close"], RSI_PERIOD)
    df["cross_up"] = (df["ema_fast"] > df["ema_slow"]) & (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1))
    return df


def run_backtest(df_entry, df_trend, capital=100.0, use_macro_filter=False):
    trend_reindexed = df_trend[["uptrend"]].reindex(df_entry.index, method="ffill")
    df = df_entry.join(trend_reindexed)

    hike_windows = build_hike_block_windows() if use_macro_filter else []

    position = None
    trades = []
    equity = capital

    for ts, row in df.iterrows():
        price = row["close"]

        if position is None:
            entry_ok = (
                bool(row.get("uptrend", False))
                and row["cross_up"]
                and RSI_LOW <= row["rsi"] <= RSI_HIGH
            )
            if use_macro_filter and entry_ok and is_blocked(ts, hike_windows):
                entry_ok = False

            if entry_ok:
                position = {"entry_price": price, "entry_time": ts}
            continue

        entry_price = position["entry_price"]
        change = (price - entry_price) / entry_price
        trend_flipped = not bool(row.get("uptrend", True))

        exit_reason = None
        if change >= TAKE_PROFIT_PCT:
            exit_reason = "TP"
        elif change <= -STOP_LOSS_PCT:
            exit_reason = "SL"
        elif trend_flipped:
            exit_reason = "trend_flip"

        if exit_reason:
            net_pnl_pct = change - 2 * FEE_PCT
            equity *= (1 + net_pnl_pct)
            trades.append({"pnl_pct": net_pnl_pct})
            position = None

    return trades, equity


def summarize(trades, equity, df, capital, label):
    n = len(trades)
    if n == 0:
        print(f"{label}: Sdelok: 0 (net signalov za period)")
        return

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    win_rate = len(wins) / n * 100

    gross_profit = sum(t["pnl_pct"] for t in wins)
    gross_loss = -sum(t["pnl_pct"] for t in losses)
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    bot_return = (equity / capital - 1) * 100
    buy_hold = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100

    eq_curve = [capital]
    e = capital
    for t in trades:
        e *= (1 + t["pnl_pct"])
        eq_curve.append(e)
    eq_curve = pd.Series(eq_curve)
    running_max = eq_curve.cummax()
    drawdown = ((eq_curve - running_max) / running_max).min() * -100

    print(f"{label}:")
    print(f"  Sdelok: {n} | Win rate: {win_rate:.1f}% | Dohodnost: {bot_return:+.2f}% | "
          f"Buy&Hold: {buy_hold:+.2f}% | Prosadka: {drawdown:.2f}% | PF: {pf:.2f}")


def main():
    print("#" * 70)
    print(f"# TREND FILTER + RSI/MA + MAKRO-FILTR PO STAVKE FRS - {SYMBOL} (2022-2024)")
    print("#" * 70)
    print()

    start = pd.Timestamp(START_DATE, tz=timezone.utc)
    end = pd.Timestamp(END_DATE, tz=timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    print(f"Zagruzhayu dannye s Binance ({TREND_TF} i {ENTRY_TF})...")
    df_trend_raw = fetch_klines(SYMBOL, TREND_TF, start_ms, end_ms)
    df_entry_raw = fetch_klines(SYMBOL, ENTRY_TF, start_ms, end_ms)
    print(f"Polucheno {len(df_trend_raw)} svechej ({TREND_TF}), {len(df_entry_raw)} svechej ({ENTRY_TF})\n")

    df_trend = prepare_trend(df_trend_raw)
    df_entry = prepare_entry(df_entry_raw)

    n_hikes = sum(1 for _, d in FOMC_HISTORY if d == "hike")
    print(f"Vsego povyshenij stavki v period: {n_hikes} (kazhdoe blokiruet vhody na {MACRO_BLOCK_DAYS} dnej)\n")

    print("=" * 70)
    print("SRAVNENIE: BEZ makro-filtra vs S makro-filtrom")
    print("=" * 70)

    trades_base, equity_base = run_backtest(df_entry, df_trend, capital=100.0, use_macro_filter=False)
    summarize(trades_base, equity_base, df_entry, 100.0, "BEZ makro-filtra")
    print()

    trades_macro, equity_macro = run_backtest(df_entry, df_trend, capital=100.0, use_macro_filter=True)
    summarize(trades_macro, equity_macro, df_entry, 100.0, "S makro-filtrom (blok posle hike)")

    print()
    print("=" * 70)
    print("Kak chitat rezultaty:")
    print("- Sravni PF i prosadku v oboih variantah - esli s filtrom PF vyshe")
    print("  i/ili prosadka nizhe, makro-filtr realno pomogaet strategii.")
    print("- Esli sdelok stalo zametno menshe, no PF vyros - filtr otsek imenno")
    print("  ubytochnye sdelki, ne prosto sluchayno umenshil aktivnost.")
    print("- Eto ne garantiya na buduschee - stavka FRS mozhet vesti sebya")
    print("  po-drugomu v drugie periody, no na 2022-2024 est realnaya proverka.")
    print("=" * 70)


if __name__ == "__main__":
    main()
