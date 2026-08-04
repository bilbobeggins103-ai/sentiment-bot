"""
Бэктест sentiment-стратегии на исторических новостях (CryptoPanic + Binance).
"""

import os
import time
from datetime import datetime, timedelta, timezone

import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from crypto_lexicon import CRYPTO_LEXICON
import config

CRYPTOPANIC_BASE_URL = "https://cryptopanic.com/api/v2/posts/"
MAX_POSTS = 1000
MAX_PAGES = 60
PRICE_HISTORY_DAYS = 90


def load_auth_token():
    token = os.environ.get("CRYPTOPANIC_TOKEN")
    if token:
        return token
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line.startswith("CRYPTOPANIC_TOKEN="):
                    return line.split("=", 1)[1].strip()
    return None


def fetch_archive_articles():
    token = load_auth_token()
    if not token:
        print("[ERROR] CRYPTOPANIC_TOKEN не найден. Создай файл .env со строкой:")
        print("        CRYPTOPANIC_TOKEN=твой_токен")
        return []

    all_articles = []
    url = CRYPTOPANIC_BASE_URL
    params = {"auth_token": token, "currencies": "BTC,ETH", "public": "true"}
    page = 0

    while url and page < MAX_PAGES and len(all_articles) < MAX_POSTS:
        try:
            resp = requests.get(url, params=params if page == 0 else None, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[WARN] Ошибка на странице {page}: {e}")
            break

        results = data.get("results", [])
        if not results:
            print(f"[INFO] Страница {page}: пусто, останавливаемся")
            break

        all_articles.extend(results)
        oldest = results[-1].get("published_at", "?")
        print(f"[INFO] Страница {page}: +{len(results)} постов (всего {len(all_articles)}, дошли до {oldest})")

        url = data.get("next")
        page += 1
        time.sleep(0.3)

    return all_articles


def extract_title_and_date(article):
    title = article.get("title") or ""
    date_str = article.get("published_at") or article.get("created_at")
    if not title or not date_str:
        return None, None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return title, None
    return title, dt.date()


def build_daily_sentiment(articles):
    analyzer = SentimentIntensityAnalyzer()
    analyzer.lexicon.update(CRYPTO_LEXICON)
    daily = {}
    skipped_no_date = 0
    skipped_irrelevant = 0

    for article in articles:
        title, date = extract_title_and_date(article)
        if not title or not date:
            skipped_no_date += 1
            continue
        lowered = title.lower()
        if config.RELEVANT_KEYWORDS and not any(kw in lowered for kw in config.RELEVANT_KEYWORDS):
            skipped_irrelevant += 1
            continue
        score = analyzer.polarity_scores(title)["compound"]
        daily.setdefault(date, []).append(score)

    print(f"[INFO] Пропущено без даты: {skipped_no_date}, нерелевантных: {skipped_irrelevant}")
    return daily


def fetch_daily_btc_prices(days=PRICE_HISTORY_DAYS):
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": "1d", "limit": days + 5},
            timeout=15,
        )
        resp.raise_for_status()
        klines = resp.json()
    except Exception as e:
        print(f"[ERROR] Не удалось получить цены BTC: {e}")
        return {}

    prices = {}
    for k in klines:
        open_time_ms, close_price = k[0], float(k[4])
        date = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc).date()
        prices[date] = close_price
    return prices


def run_backtest(daily_sentiment, daily_prices):
    dates = sorted(daily_sentiment.keys())
    trades = []
    for date in dates:
        scores = daily_sentiment[date]
        n = len(scores)
        avg = sum(scores) / n if n else 0.0
        if n < config.MIN_HEADLINES_FOR_SIGNAL:
            continue
        if avg >= config.BUY_THRESHOLD:
            action = "BUY"
        elif avg <= config.SELL_THRESHOLD:
            action = "SELL"
        else:
            continue

        next_date = date + timedelta(days=1)
        price_today = daily_prices.get(date)
        price_next = daily_prices.get(next_date)
        if price_today is None or price_next is None:
            continue

        pct_change = (price_next - price_today) / price_today * 100
        correct = (action == "BUY" and pct_change > 0) or (action == "SELL" and pct_change < 0)

        trades.append({
            "date": date, "action": action, "avg_sentiment": round(avg, 3),
            "n_headlines": n, "price_today": price_today, "price_next": price_next,
            "pct_change": round(pct_change, 2), "correct": correct,
        })
    return trades


def print_report(trades):
    if not trades:
        print("\n[РЕЗУЛЬТАТ] Ни одного сигнала BUY/SELL не сгенерировано за период.")
        print("Возможно, пороги слишком строгие для объёма собранных новостей.")
        return

    total = len(trades)
    correct = sum(1 for t in trades if t["correct"])
    buys = sum(1 for t in trades if t["action"] == "BUY")
    sells = total - buys

    print(f"\n{'='*60}")
    print(f"РЕЗУЛЬТАТЫ БЭКТЕСТА")
    print(f"{'='*60}")
    print(f"Всего сигналов: {total} (BUY: {buys}, SELL: {sells})")
    print(f"Угадано направление: {correct}/{total} ({correct/total*100:.1f}%)")
    print(f"\nДетали по каждому сигналу:")
    print(f"{'Дата':<12} {'Сигнал':<6} {'Sentiment':<10} {'Заголовков':<11} {'Изм.цены %':<11} {'Верно?'}")
    for t in trades:
        mark = "OK" if t["correct"] else "X"
        print(f"{str(t['date']):<12} {t['action']:<6} {t['avg_sentiment']:<10} "
              f"{t['n_headlines']:<11} {t['pct_change']:<11} {mark}")


def main():
    print("[START] Бэктест sentiment-стратегии (глубина зависит от пагинации CryptoPanic)")
    print(f"Пороги: BUY >= {config.BUY_THRESHOLD}, SELL <= {config.SELL_THRESHOLD}, "
          f"мин. заголовков = {config.MIN_HEADLINES_FOR_SIGNAL}\n")

    print("[1/3] Тянем исторические новости...")
    articles = fetch_archive_articles()
    print(f"Всего собрано статей: {len(articles)}\n")

    print("[2/3] Считаем sentiment по дням...")
    daily_sentiment = build_daily_sentiment(articles)
    print(f"Дней с данными: {len(daily_sentiment)}\n")

    print("[3/3] Тянем исторические цены BTC...")
    daily_prices = fetch_daily_btc_prices()
    print(f"Дней с ценами: {len(daily_prices)}\n")

    trades = run_backtest(daily_sentiment, daily_prices)
    print_report(trades)


if __name__ == "__main__":
    main()
