"""
Sentiment-analiz krypto-novostej - prozrachnyj, bez "chernogo yaschika"
==========================================================================

Chto delaet skript:
1. Chitaet svezhie zagolovki novostej s besplatnyh RSS-lent (CoinDesk, Cointelegraph)
2. Ocenivaet tonalnost kazhdogo zagolovka metodom VADER - eto NE nejroset,
   a prozrachnyj slovarnyj metod: u kazhdogo slova est zaranee izvestnyj
   "ball" (naprimer "surge" = +2.1, "crash" = -3.4), plyus pravila dlya
   otricanij ("not good" perevorachivaet znak) i usilenij (CAPS, "!!!").
   Mozhno posmotret slovar celikom - eto ne magiya, a tablica chisel.
3. Schitaet srednyuyu tonalnost po vsem svezhim novostyam
4. Loguet rezultat v CSV-fajl kazhdyj raz pri zapuske - so vremenem, esli
   zapuskat skript kazhdyj den, nakopitsya svoya istoriya dlya proverki
   korrelyacii s cenoj (tak zhe, kak my proverjali DXY i stavku FRS).

VAZHNO: eto NE bektest na istoricheskih dannyh - besplatnyh istoricheskih
arhivov novostej net. Eto "live"-monitor, kotoryj nakaplivaet dannye
so vremenem. Chestnaya provkerka korrelyacii budet vozmozhna cherez
neskolko nedel/mesyacev nabludeniya.

Trebovaniya: pip install vaderSentiment feedparser requests
Zapusk:     python news_sentiment.py
"""

import csv
import os
import time
from datetime import datetime, timezone

import feedparser
import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

RSS_FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
}

BINANCE_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"

# Krypto-specificheskij slovar - VADER po umolchaniyu ne znaet finansovyj zhargon.
# Kazhdoe slovo - eto prosto chislo ot -4 (maksimalno negativno) do +4 (maksimalno
# pozitivno), tochno tak zhe kak i original'nyj slovar VADER. Mozhno menyat/dobavlyat
# svoi slova - eto obychnyj Python-slovar, nikakoj magii.
CRYPTO_LEXICON = {
    # pozitivnye terminy
    "surge": 2.5, "surges": 2.5, "surging": 2.5, "surged": 2.5,
    "rally": 2.3, "rallies": 2.3, "rallying": 2.3,
    "moon": 2.0, "mooning": 3.0,
    "bullish": 2.5,
    "breakout": 2.0,
    "ath": 2.5,
    "adoption": 1.8,
    "gains": 2.0,
    "outperform": 2.0, "outperforms": 2.0,
    "upgrade": 1.5, "upgrades": 1.5,
    "partnership": 1.5,
    "soar": 2.5, "soars": 2.5, "soaring": 2.5,
    "rebound": 1.8, "rebounds": 1.8,
    # negativnye terminy
    "crash": -2.9, "crashes": -2.9, "crashing": -2.9, "crashed": -2.9,
    "dump": -2.0, "dumping": -2.0, "dumped": -2.0,
    "bearish": -2.5,
    "sell-off": -2.3, "selloff": -2.3,
    "liquidation": -2.5, "liquidated": -2.5, "liquidations": -2.5,
    "hack": -2.8, "hacked": -2.8, "hacker": -2.0, "hackers": -2.0,
    "exploit": -2.3, "exploited": -2.3,
    "rug": -2.5, "rugpull": -3.0,
    "scam": -3.0, "scammed": -3.0,
    "banned": -2.5, "ban": -2.0,
    "crackdown": -2.3,
    "lawsuit": -1.8, "sued": -1.8, "sues": -1.8,
    "delist": -2.0, "delisting": -2.0, "delisted": -2.0,
    "plunge": -2.7, "plunges": -2.7, "plunged": -2.7,
    "plummet": -2.7, "plummets": -2.7, "plummeted": -2.7,
    "collapse": -2.8, "collapses": -2.8, "collapsed": -2.8,
    "insolvency": -2.5, "insolvent": -2.5,
    "bankrupt": -2.8, "bankruptcy": -2.8,
    "fud": -1.5,
    "capitulation": -2.0,
}

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

LOG_FILE = "sentiment_log.csv"
MAX_HEADLINES_PER_FEED = 20


def fetch_headlines():
    """Chitaem svezhie zagolovki s RSS-lent. Vozvraschaet spisok (istochnik, zagolovok)."""
    headlines = []
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:MAX_HEADLINES_PER_FEED]:
                headlines.append((source, entry.title))
        except Exception as e:
            print(f"  Oshibka zagruzki {source}: {e}")
    return headlines


def score_sentiment(headlines, analyzer):
    """
    Schitaem tonalnost kazhdogo zagolovka cherez VADER.
    compound: chislo ot -1 (maksimalno negativno) do +1 (maksimalno pozitivno).
    """
    results = []
    for source, title in headlines:
        scores = analyzer.polarity_scores(title)
        results.append({
            "source": source,
            "title": title,
            "compound": scores["compound"],
            "pos": scores["pos"],
            "neg": scores["neg"],
            "neu": scores["neu"],
        })
    return results


def fetch_prices():
    """Tekuschie ceny BTC i ETH s Binance - dlya konteksta v loge."""
    prices = {}
    for symbol in SYMBOLS:
        try:
            resp = requests.get(BINANCE_PRICE_URL, params={"symbol": symbol}, timeout=10)
            resp.raise_for_status()
            prices[symbol] = float(resp.json()["price"])
        except Exception as e:
            prices[symbol] = None
    return prices


def log_to_csv(avg_compound, n_headlines, prices):
    """Dobavlyaem stroku v CSV - so vremenem nakopitsya istoriya dlya analiza."""
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp_utc", "avg_sentiment", "n_headlines", "btc_price", "eth_price"])
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            f"{avg_compound:.4f}",
            n_headlines,
            prices.get("BTCUSDT", ""),
            prices.get("ETHUSDT", ""),
        ])


def main():
    print("#" * 70)
    print("# SENTIMENT-ANALIZ KRYPTO-NOVOSTEJ (VADER, prozrachnyj metod)")
    print("#" * 70)
    print()

    analyzer = SentimentIntensityAnalyzer()
    analyzer.lexicon.update(CRYPTO_LEXICON)

    print(f"Rasshiril slovar VADER na {len(CRYPTO_LEXICON)} krypto-terminov")
    print("(surge, crash, moon, rug, hacked i t.d. - teper raspoznayutsya)\n")

    print("Chitayu svezhie novosti s RSS-lent...")
    headlines = fetch_headlines()
    print(f"Polucheno {len(headlines)} zagolovkov\n")

    if not headlines:
        print("Ne udalos zagruzit ni odnoj novosti. Proverte internet-soedinenie.")
        return

    scored = score_sentiment(headlines, analyzer)

    print("=" * 70)
    print("ZAGOLOVKI I IH TONALNOST (compound: -1 negativno .. +1 pozitivno)")
    print("=" * 70)
    for item in sorted(scored, key=lambda x: x["compound"]):
        marker = "POZITIV" if item["compound"] > 0.05 else ("NEGATIV" if item["compound"] < -0.05 else "nejtral")
        print(f"[{item['compound']:+.3f}] ({marker:7s}) [{item['source']}] {item['title']}")

    avg_compound = sum(s["compound"] for s in scored) / len(scored)
    n_positive = sum(1 for s in scored if s["compound"] > 0.05)
    n_negative = sum(1 for s in scored if s["compound"] < -0.05)
    n_neutral = len(scored) - n_positive - n_negative

    print()
    print("=" * 70)
    print("SVODKA")
    print("=" * 70)
    print(f"Vsego zagolovkov: {len(scored)}")
    print(f"Pozitivnyh: {n_positive} | Negativnyh: {n_negative} | Nejtralnyh: {n_neutral}")
    print(f"Srednyaya tonalnost (compound): {avg_compound:+.4f}")
    print()

    print("Zagruzhayu tekuschie ceny BTC/ETH dlya konteksta v loge...")
    prices = fetch_prices()
    for symbol, price in prices.items():
        if price:
            print(f"  {symbol}: ${price:,.2f}")

    log_to_csv(avg_compound, len(scored), prices)
    print(f"\nRezultat dobavlen v {LOG_FILE} (nakaplivaetsya istoriya so vremenem)")

    print()
    print("=" * 70)
    print("Kak chitat rezultaty:")
    print("- 'Compound' - eto NE predskazanie ceny, a prosto chislo, pokazyvayuschee")
    print("  obschij ton zagolovka na osnove slovarya izvestnyh slov. Mozhno")
    print("  proverit vruchnuyu: slovo 'surge' (rost) daet plyus, 'crash' (obval) - minus.")
    print("- Odin zapusk skripta nichego ne dokazyvaet - nuzhno nakopit dannye")
    print("  za neskolko nedel (zapuskat skript kazhdyj den ili neskolko raz v den),")
    print("  a potom sravnit sentiment_log.csv s realnym dvizheniem ceny.")
    print("- Eto polnostju prozrachnyj metod - v otlichie ot 'chernogo yaschika',")
    print("  kazhdyj ball mozhno proverit i ob'yasnit.")
    print("=" * 70)


if __name__ == "__main__":
    main()
