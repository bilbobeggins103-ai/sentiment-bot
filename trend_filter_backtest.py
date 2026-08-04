"""
Гибридная стратегия: Trend Filter + RSI/MA Entry + Fear&Greed фильтр
=====================================================================

Идея:
- Старший таймфрейм (1h) определяет ТРЕНД: EMA50 > EMA200 -> аптренд (разрешены лонги).
- Младший таймфрейм (15m) даёт ТОЧКУ ВХОДА: пересечение EMA9/EMA21 вверх,
  подтверждённое RSI(14) в диапазоне 40-70 (не перекуплено, не падающий нож).
- Fear&Greed Index (alternative.me) — доп. фильтр по сентименту рынка:
  не входим в лонг, если индекс в зоне "Extreme Greed" (рынок перегрет по настроениям).
- Выход: TP/SL по проценту ИЛИ разворот тренда (EMA50 пересекает EMA200 вниз на 1h).

Скрипт прогоняет бэктест ДВАЖДЫ на каждом периоде — с фильтром сентимента и без —
чтобы сразу было видно, помогает он PF или нет.

Требования: pip install pandas numpy requests
Запуск:     python trend_filter_backtest.py
"""

import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
FNG_URL = "https://api.alternative.me/fng/"

SYMBOL = "ETHUSDT"           # поменяй на свою пару, если торгуешь другим активом
TREND_TF = "1h"
ENTRY_TF = "15m"

# --- параметры стратегии (можно крутить для оптимизации) ---
TREND_FAST, TREND_SLOW = 50, 200      # EMA на старшем ТФ для определения тренда
ENTRY_FAST, ENTRY_SLOW = 9, 21        # EMA на младшем ТФ для точки входа
RSI_PERIOD = 14
RSI_LOW, RSI_HIGH = 40, 70            # RSI должен быть в этом коридоре при входе
STOP_LOSS_PCT = 0.015                 # 1.5%
TAKE_PROFIT_PCT = 0.03                # 3% (RR ~ 1:2)
FEE_PCT = 0.001                       # 0.1% комиссия за сделку (Binance/Uniswap примерно)

# --- Fear & Greed фильтр ---
FNG_GREED_THRESHOLD = 75   # выше этого - "Extreme Greed", лонги запрещены
FNG_FEAR_THRESHOLD = 25    # ниже этого - "Extreme Fear" (пока не используется как доп. смягчение, но полезно для анализа)

TEST_PERIODS_DAYS = [14, 30, 60, 90]


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Тянем свечи с Binance public API постранично (лимит 1000 свечей за запрос)."""
    all_rows = []
    cur = start_ms
    while cur < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cur,
            "endTime": end_ms,
            "limit": 1000,
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
        time.sleep(0.2)  # не долбим API слишком часто

    df = pd.DataFrame(all_rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore"
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.set_index("open_time", inplace=True)
    return df[["open", "high", "low", "close", "volume"]]


def fetch_fear_greed() -> pd.DataFrame:
    """Тянем полную историю Fear&Greed Index с alternative.me (бесплатно, без ключа)."""
    resp = requests.get(FNG_URL, params={"limit": 0, "format": "json"}, timeout=15)
    resp.raise_for_status()
    data = resp.json()["data"]

    df = pd.DataFrame(data)
    df["value"] = df["value"].astype(int)
    df["date"] = pd.to_datetime(df["timestamp"].astype(int), unit="s", utc=True).dt.floor("D")
    df = df[["date", "value"]].rename(columns={"value": "fng"})
    df = df.sort_values("date").set_index("date")
    return df


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def prepare_trend(df_trend: pd.DataFrame) -> pd.DataFrame:
    df = df_trend.copy()
    df["ema_fast"] = df["close"].ewm(span=TREND_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=TREND_SLOW, adjust=False).mean()
    df["uptrend"] = df["ema_fast"] > df["ema_slow"]
    return df


def prepare_entry(df_entry: pd.DataFrame) -> pd.DataFrame:
    df = df_entry.copy()
    df["ema_fast"] = df["close"].ewm(span=ENTRY_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=ENTRY_SLOW, adjust=False).mean()
    df["rsi"] = rsi(df["close"], RSI_PERIOD)
    df["cross_up"] = (df["ema_fast"] > df["ema_slow"]) & (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1))
    return df


def run_backtest(df_entry: pd.DataFrame, df_trend: pd.DataFrame, capital: float = 100.0,
                  use_fng_filter: bool = False):
    # маппим тренд на каждую 15m свечу (последнее известное значение с 1h)
    trend_reindexed = df_trend[["uptrend"]].reindex(df_entry.index, method="ffill")
    df = df_entry.join(trend_reindexed)

    position = None  # dict: entry_price, entry_time
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
            if use_fng_filter and entry_ok:
                fng_value = row.get("fng")
                if pd.notna(fng_value) and fng_value > FNG_GREED_THRESHOLD:
                    entry_ok = False  # рынок в "Extreme Greed" - пропускаем сигнал
            if entry_ok:
                position = {"entry_price": price, "entry_time": ts}
            continue

        # в позиции - проверяем условия выхода
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
            gross_pnl_pct = change
            net_pnl_pct = gross_pnl_pct - 2 * FEE_PCT  # комиссия на вход и на выход
            equity *= (1 + net_pnl_pct)
            trades.append({
                "entry_time": position["entry_time"],
                "exit_time": ts,
                "entry_price": entry_price,
                "exit_price": price,
                "pnl_pct": net_pnl_pct,
                "reason": exit_reason,
            })
            position = None

    return trades, equity


def summarize(trades, capital, equity, df_entry):
    n = len(trades)
    if n == 0:
        buy_hold = (df_entry["close"].iloc[-1] / df_entry["close"].iloc[0] - 1) * 100
        print(f"Сделок: 0 | Win rate: 0.0% | Доходность бота: +0.00% | "
              f"Buy&Hold: {buy_hold:+.2f}% | Просадка: 0.00% | PF: inf")
        return

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    win_rate = len(wins) / n * 100

    gross_profit = sum(t["pnl_pct"] for t in wins)
    gross_loss = -sum(t["pnl_pct"] for t in losses)
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    bot_return = (equity / capital - 1) * 100
    buy_hold = (df_entry["close"].iloc[-1] / df_entry["close"].iloc[0] - 1) * 100

    # максимальная просадка по equity curve
    eq_curve = [capital]
    e = capital
    for t in trades:
        e *= (1 + t["pnl_pct"])
        eq_curve.append(e)
    eq_curve = pd.Series(eq_curve)
    running_max = eq_curve.cummax()
    drawdown = ((eq_curve - running_max) / running_max).min() * -100

    print(f"Сделок: {n} | Win rate: {win_rate:.1f}% | Доходность бота: {bot_return:+.2f}% | "
          f"Buy&Hold: {buy_hold:+.2f}% | Просадка: {drawdown:.2f}% | PF: {pf:.2f}")


def main():
    print("#" * 60)
    print(f"# TREND FILTER (EMA{TREND_FAST}/{TREND_SLOW} 1h) + RSI/MA ENTRY (15m) — {SYMBOL}")
    print("#" * 60)
    print()

    now = datetime.now(timezone.utc)
    max_days = max(TEST_PERIODS_DAYS)
    # берём с запасом (+TREND_SLOW часов) чтобы EMA200 на 1h успела "прогреться"
    start = now - timedelta(days=max_days, hours=TREND_SLOW * 2)

    start_ms = int(start.timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)

    print("Загружаю данные с Binance...")
    df_trend_raw = fetch_klines(SYMBOL, TREND_TF, start_ms, end_ms)
    df_entry_raw = fetch_klines(SYMBOL, ENTRY_TF, start_ms, end_ms)
    print(f"Получено {len(df_trend_raw)} свечей ({TREND_TF}) и {len(df_entry_raw)} свечей ({ENTRY_TF})")

    print("Загружаю Fear&Greed Index (alternative.me)...")
    df_fng = fetch_fear_greed()
    print(f"Получено {len(df_fng)} дневных значений индекса\n")

    df_trend = prepare_trend(df_trend_raw)
    df_entry = prepare_entry(df_entry_raw)

    # маппим дневной FNG на каждую 15m свечу по дате (последнее известное значение)
    df_entry["date"] = df_entry.index.floor("D")
    df_entry = df_entry.join(df_fng, on="date")
    df_entry["fng"] = df_entry["fng"].ffill()

    for days in TEST_PERIODS_DAYS:
        cutoff = now - timedelta(days=days)
        df_entry_period = df_entry[df_entry.index >= cutoff]
        df_trend_period = df_trend[df_trend.index >= cutoff - timedelta(hours=TREND_SLOW * 2)]

        print(f"--- Период: последние {days} дней ({ENTRY_TF}) ---")

        print("  Без Fear&Greed фильтра: ", end="")
        trades_base, equity_base = run_backtest(df_entry_period, df_trend_period, capital=100.0,
                                                 use_fng_filter=False)
        summarize(trades_base, 100.0, equity_base, df_entry_period)

        print("  С Fear&Greed фильтром:  ", end="")
        trades_fng, equity_fng = run_backtest(df_entry_period, df_trend_period, capital=100.0,
                                               use_fng_filter=True)
        summarize(trades_fng, 100.0, equity_fng, df_entry_period)
        print()

    print("=" * 60)
    print("Как читать результаты:")
    print("- Сравнивай PF и просадку 'без фильтра' vs 'с фильтром' на каждом периоде.")
    print("- Если фильтр систематически поднимает PF и/или снижает просадку —")
    print(f"  сентимент (Extreme Greed > {FNG_GREED_THRESHOLD}) даёт полезный сигнал на этой паре.")
    print("- Если разницы почти нет (мало сделок попадает в зону Extreme Greed) —")
    print("  фильтр либо не влияет, либо порог нужно снизить (например, до 65-70).")
    print("- Не делай выводов по 1-2 периодам — совпадения возможны на любом наборе данных.")
    print("=" * 60)


if __name__ == "__main__":
    main()
