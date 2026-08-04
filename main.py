"""
Главный цикл sentiment-бота.
Запуск: python main.py
Останов: Ctrl+C
"""

import csv
import os
import time
from datetime import datetime, timezone

import config
from sentiment_engine import SentimentEngine
from decision_engine import DecisionEngine
from trader import get_prices, execute_trade


def ensure_log_header(path, header):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(header)


def log_sentiment(avg_sentiment, n_headlines, btc_price, eth_price):
    ensure_log_header(
        config.SENTIMENT_LOG_FILE,
        ["timestamp_utc", "avg_sentiment", "n_headlines", "btc_price", "eth_price"],
    )
    with open(config.SENTIMENT_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            datetime.now(timezone.utc).isoformat(),
            round(avg_sentiment, 4),
            n_headlines,
            btc_price,
            eth_price,
        ])


def log_trade(action, avg_sentiment, n_headlines, btc_price, eth_price):
    ensure_log_header(
        config.TRADE_LOG_FILE,
        ["timestamp_utc", "action", "avg_sentiment", "n_headlines", "btc_price", "eth_price", "mode"],
    )
    with open(config.TRADE_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            datetime.now(timezone.utc).isoformat(),
            action,
            round(avg_sentiment, 4),
            n_headlines,
            btc_price,
            eth_price,
            config.MODE,
        ])


def main():
    print(f"[START] Sentiment-бот запущен. Режим: {config.MODE}. "
          f"Опрос RSS каждые {config.POLL_INTERVAL_SECONDS} сек.")

    engine = SentimentEngine()
    decider = DecisionEngine()

    while True:
        try:
            new_headlines = engine.process_new_headlines()
            for title, score in new_headlines:
                print(f"[NEWS] ({score:+.3f}) {title}")

            avg_sentiment, n_headlines = engine.get_window_stats()
            btc_price, eth_price = get_prices()

            # Логируем состояние sentiment каждый цикл (как раньше делал CryptoSentimentDaily,
            # только теперь чаще - раз в POLL_INTERVAL_SECONDS, а не раз в день)
            log_sentiment(avg_sentiment, n_headlines, btc_price, eth_price)

            action = decider.decide(avg_sentiment, n_headlines)
            print(f"[STATUS] avg_sentiment={avg_sentiment:+.3f} "
                  f"n_headlines={n_headlines} -> {action}")

            if action in ("BUY", "SELL"):
                success = execute_trade(action, avg_sentiment, n_headlines)
                if success:
                    decider.mark_trade_executed()
                    log_trade(action, avg_sentiment, n_headlines, btc_price, eth_price)

        except Exception as e:
            print(f"[ERROR] Сбой в основном цикле: {e}")

        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
