"""
Decision engine: превращает (avg_sentiment, n_headlines) в BUY/SELL/HOLD
с учётом минимального числа заголовков и cooldown между сделками.

Cooldown сохраняется на диск (last_trade.json), потому что при запуске
через GitHub Actions каждый вызов - новый процесс без общей памяти.
"""

import json
import os
import time
import config


class DecisionEngine:
    def __init__(self):
        self.last_trade_ts = self._load_last_trade_ts()

    def _load_last_trade_ts(self):
        if not os.path.exists(config.LAST_TRADE_FILE):
            return 0.0
        try:
            with open(config.LAST_TRADE_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("last_trade_ts", 0.0)
        except (json.JSONDecodeError, ValueError):
            return 0.0

    def _save_last_trade_ts(self):
        with open(config.LAST_TRADE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_trade_ts": self.last_trade_ts}, f)

    def decide(self, avg_sentiment: float, n_headlines: int) -> str:
        if n_headlines < config.MIN_HEADLINES_FOR_SIGNAL:
            return "HOLD"

        if self._in_cooldown():
            return "HOLD"

        if avg_sentiment >= config.BUY_THRESHOLD:
            return "BUY"
        elif avg_sentiment <= config.SELL_THRESHOLD:
            return "SELL"
        else:
            return "HOLD"

    def _in_cooldown(self) -> bool:
        return (time.time() - self.last_trade_ts) < config.TRADE_COOLDOWN_SECONDS

    def mark_trade_executed(self):
        self.last_trade_ts = time.time()
        self._save_last_trade_ts()
