"""
Pairs Trading (Relative Value) — ETH/BTC ротация без шорта
============================================================

Идея (statistical arbitrage, но long-only, т.к. торговля на DEX без шорта):

- Смотрим не на абсолютную цену ETH, а на СООТНОШЕНИЕ ETH/BTC.
- Считаем rolling Z-score этого соотношения (насколько сильно оно отклонилось
  от своего среднего за последние N баров, в стандартных отклонениях).
- Если ETH статистически ДЕШЁВ относительно BTC (Z сильно отрицательный) —
  держим ETH, ждём возврата к среднему (mean reversion).
- Если ETH статистически ДОРОГ относительно BTC (Z сильно положительный) —
  перекладываемся в BTC (вместо шорта ETH, которого у нас нет).
- Когда Z возвращается к нейтральной зоне — просто держим то, что держим,
  до следующего сигнала (не мечемся туда-сюда на каждом шуме).

Это статистический, а не визуальный сигнал — на графике свечей ETH его не видно,
он существует только в соотношении двух активов.

Требования: pip install pandas numpy requests
Запуск:     python pairs_trading_backtest.py
"""

import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

SYMBOL_A = "ETHUSDT"   # "рисковый" актив
SYMBOL_B = "BTCUSDT"   # "базовый" актив, в него перекладываемся при дороговизне A
INTERVAL = "1h"

# --- параметры стратегии ---
ZSCORE_WINDOW = 100      # окно для расчёта rolling mean/std логарифмического соотношения (в барах)
Z_ENTRY = 1.5            # порог отклонения для входа (в std) - выше него считаем "дорого/дёшево"
Z_EXIT = 0.3             # порог возврата к среднему - используем для более мягкого выхода/переключения
FEE_PCT = 0.001          # 0.1% комиссия за сделку при переключении между активами

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
        time.sleep(0.2)

    df = pd.DataFrame(all_rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore"
    ])
    df["close"] = df["close"].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.set_index("open_time", inplace=True)
    return df[["close"]]


def build_ratio_frame(df_a: pd.DataFrame, df_b: pd.DataFrame) -> pd.DataFrame:
    """Собираем общий датафрейм с логарифмическим соотношением цен и Z-score."""
    df = pd.DataFrame(index=df_a.index)
    df["price_a"] = df_a["close"]
    df["price_b"] = df_b["close"].reindex(df_a.index, method="ffill")
    df["log_ratio"] = np.log(df["price_a"] / df["price_b"])

    roll_mean = df["log_ratio"].rolling(ZSCORE_WINDOW).mean()
    roll_std = df["log_ratio"].rolling(ZSCORE_WINDOW).std()
    df["zscore"] = (df["log_ratio"] - roll_mean) / roll_std
    return df


def run_backtest(df: pd.DataFrame, capital: float = 100.0):
    """
    Ротация long-only между активом A (ETH) и активом B (BTC) на основе Z-score
    их логарифмического соотношения. Возвращает список переключений и equity curve.
    """
    position = "A"   # с чего стартуем - держим ETH по умолчанию
    equity = capital
    switches = []
    equity_curve = []

    prev_price_a = None
    prev_price_b = None

    for ts, row in df.iterrows():
        price_a, price_b, z = row["price_a"], row["price_b"], row["zscore"]

        # применяем доходность за бар к текущей позиции (кроме самого первого бара)
        if prev_price_a is not None:
            if position == "A":
                equity *= (price_a / prev_price_a)
            elif position == "B":
                equity *= (price_b / prev_price_b)

        # решаем, нужно ли переключиться (только если Z-score не NaN, т.е. окно прогрето)
        if pd.notna(z):
            new_position = position
            if z >= Z_ENTRY and position != "B":
                new_position = "B"   # ETH дорог относительно BTC -> перекладываемся в BTC
            elif z <= -Z_ENTRY and position != "A":
                new_position = "A"   # ETH дёшев относительно BTC -> держим ETH

            if new_position != position:
                equity *= (1 - FEE_PCT)  # комиссия за переключение
                switches.append({"time": ts, "from": position, "to": new_position, "zscore": z})
                position = new_position

        equity_curve.append(equity)
        prev_price_a, prev_price_b = price_a, price_b

    return switches, equity_curve


def summarize(switches, equity_curve, df, capital):
    if len(equity_curve) == 0:
        print("Недостаточно данных для расчёта.")
        return

    final_equity = equity_curve[-1]
    bot_return = (final_equity / capital - 1) * 100

    buy_hold_a = (df["price_a"].iloc[-1] / df["price_a"].iloc[0] - 1) * 100
    buy_hold_b = (df["price_b"].iloc[-1] / df["price_b"].iloc[0] - 1) * 100

    eq_series = pd.Series(equity_curve)
    running_max = eq_series.cummax()
    drawdown = ((eq_series - running_max) / running_max).min() * -100

    n_switches = len(switches)

    print(f"Переключений: {n_switches} | Доходность стратегии: {bot_return:+.2f}% | "
          f"Buy&Hold ETH: {buy_hold_a:+.2f}% | Buy&Hold BTC: {buy_hold_b:+.2f}% | "
          f"Просадка: {drawdown:.2f}%")


def main():
    print("#" * 70)
    print(f"# PAIRS TRADING (relative value): {SYMBOL_A} vs {SYMBOL_B} — long-only ротация")
    print("#" * 70)
    print()

    now = datetime.now(timezone.utc)
    max_days = max(TEST_PERIODS_DAYS)
    # запас в барах на прогрев rolling-окна (ZSCORE_WINDOW часов сверху)
    start = now - timedelta(days=max_days, hours=ZSCORE_WINDOW * 2)

    start_ms = int(start.timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)

    print(f"Загружаю данные с Binance ({SYMBOL_A}, {SYMBOL_B}, {INTERVAL})...")
    df_a = fetch_klines(SYMBOL_A, INTERVAL, start_ms, end_ms)
    df_b = fetch_klines(SYMBOL_B, INTERVAL, start_ms, end_ms)
    print(f"Получено {len(df_a)} свечей {SYMBOL_A}, {len(df_b)} свечей {SYMBOL_B}\n")

    df = build_ratio_frame(df_a, df_b)

    for days in TEST_PERIODS_DAYS:
        cutoff = now - timedelta(days=days)
        df_period = df[df.index >= cutoff].dropna(subset=["zscore"])

        if df_period.empty:
            print(f"--- Период: последние {days} дней ({INTERVAL}) --- недостаточно данных\n")
            continue

        z_min = df_period["zscore"].min()
        z_max = df_period["zscore"].max()

        print(f"--- Период: последние {days} дней ({INTERVAL}) ---")
        print(f"  Z-score за период: min={z_min:.2f}  max={z_max:.2f}  "
              f"(порог входа ±{Z_ENTRY})")

        switches, equity_curve = run_backtest(df_period, capital=100.0)
        summarize(switches, equity_curve, df_period, 100.0)
        print()

    print("=" * 70)
    print("Как читать результаты:")
    print(f"- Z-score показывает, насколько сильно ETH/BTC отклонялось от своего")
    print(f"  {ZSCORE_WINDOW}-часового среднего. Если min/max не доходят до ±{Z_ENTRY} -")
    print("  переключений почти не будет (это не ошибка, а отсутствие экстремумов).")
    print("- Сравнивай 'Доходность стратегии' с Buy&Hold ETH и Buy&Hold BTC:")
    print("  если стратегия обгоняет ОБА бенчмарка - относительная стоимость")
    print("  даёт реальный edge. Если хуже обоих - ротация только добавляет")
    print("  комиссии без пользы.")
    print("- Малое число переключений на коротких периодах - нормально для")
    print("  mean-reversion стратегий, это не скальпинг с частыми сделками.")
    print("- Попробуй разные ZSCORE_WINDOW/Z_ENTRY - слишком короткое окно даёт")
    print("  шумные сигналы, слишком длинное - почти не реагирует.")
    print("=" * 70)


if __name__ == "__main__":
    main()
