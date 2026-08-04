"""
Один цикл sentiment-бота - для запуска через GitHub Actions по расписанию.
"""

from sentiment_engine import SentimentEngine
from decision_engine import DecisionEngine
from trader import get_prices, execute_trade
from main import log_sentiment, log_trade


def main():
    print("[RUN] Одиночный цикл sentiment-бота")

    engine = SentimentEngine()
    decider = DecisionEngine()

    new_headlines = engine.process_new_headlines()
    for title, score in new_headlines:
        print(f"[NEWS] ({score:+.3f}) {title}")

    avg_sentiment, n_headlines = engine.get_window_stats()
    btc_price, eth_price = get_prices()

    log_sentiment(avg_sentiment, n_headlines, btc_price, eth_price)

    action = decider.decide(avg_sentiment, n_headlines)
    print(f"[STATUS] avg_sentiment={avg_sentiment:+.3f} n_headlines={n_headlines} -> {action}")

    if action in ("BUY", "SELL"):
        success = execute_trade(action, avg_sentiment, n_headlines)
        if success:
            decider.mark_trade_executed()
            log_trade(action, avg_sentiment, n_headlines, btc_price, eth_price)

    print("[DONE]")


if __name__ == "__main__":
    main()
