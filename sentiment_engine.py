"""
Sentiment engine: тянет RSS, считает тональность заголовков (VADER + крипто-словарь),
хранит уже обработанные новости, чтобы не дублировать сигнал.
"""

import json
import os
import hashlib
from datetime import datetime, timezone, timedelta

import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from crypto_lexicon import CRYPTO_LEXICON
import config


class SentimentEngine:
    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()
        self.analyzer.lexicon.update(CRYPTO_LEXICON)
        self.seen_items = self._load_seen_items()
        self.recent_scores = self._load_recent_scores()

    def _load_recent_scores(self):
        if not os.path.exists(config.RECENT_SCORES_FILE):
            return []
        try:
            with open(config.RECENT_SCORES_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return [(datetime.fromisoformat(ts), score) for ts, score in raw]
        except (json.JSONDecodeError, ValueError):
            return []

    def _save_recent_scores(self):
        raw = [(ts.isoformat(), score) for ts, score in self.recent_scores]
        with open(config.RECENT_SCORES_FILE, "w", encoding="utf-8") as f:
            json.dump(raw, f)

    def _load_seen_items(self):
        if os.path.exists(config.SEEN_ITEMS_FILE):
            with open(config.SEEN_ITEMS_FILE, "r", encoding="utf-8") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}
        return {}

    def _save_seen_items(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).timestamp()
        pruned = {k: v for k, v in self.seen_items.items() if v > cutoff}
        self.seen_items = pruned
        with open(config.SEEN_ITEMS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.seen_items, f)

    @staticmethod
    def _item_id(entry):
        key = entry.get("link") or entry.get("title", "")
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_relevant(title: str) -> bool:
        if not config.RELEVANT_KEYWORDS:
            return True
        lowered = title.lower()
        return any(kw in lowered for kw in config.RELEVANT_KEYWORDS)

    def fetch_new_headlines(self):
        new_items = []
        now_ts = datetime.now(timezone.utc).timestamp()

        for feed_url in config.RSS_FEEDS:
            try:
                parsed = feedparser.parse(feed_url)
            except Exception as e:
                print(f"[WARN] Не удалось прочитать фид {feed_url}: {e}")
                continue

            for entry in parsed.entries:
                item_id = self._item_id(entry)
                if item_id in self.seen_items:
                    continue

                title = entry.get("title", "").strip()
                if not title:
                    continue

                self.seen_items[item_id] = now_ts

                if not self._is_relevant(title):
                    continue

                new_items.append(title)

        if new_items:
            self._save_seen_items()

        return new_items

    def score_headline(self, title: str) -> float:
        return self.analyzer.polarity_scores(title)["compound"]

    def process_new_headlines(self):
        headlines = self.fetch_new_headlines()
        now = datetime.now(timezone.utc)
        results = []

        for title in headlines:
            score = self.score_headline(title)
            self.recent_scores.append((now, score))
            results.append((title, score))

        self._prune_old_scores()
        self._save_recent_scores()
        return results

    def _prune_old_scores(self):
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=config.SENTIMENT_WINDOW_MINUTES)
        self.recent_scores = [(ts, s) for ts, s in self.recent_scores if ts >= cutoff]

    def get_window_stats(self):
        self._prune_old_scores()
        n = len(self.recent_scores)
        if n == 0:
            return 0.0, 0
        avg = sum(s for _, s in self.recent_scores) / n
        return avg, n
