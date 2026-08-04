"""
- get_prices(): текущие цены BTC/ETH через публичный Binance API (для логов, без ключей)
- execute_trade(): заглушка исполнения. В "paper" режиме просто логирует.
  Для "live" режима сюда нужно подключить твою существующую web3/Uniswap-логику
  (некастодиальный кошелёк на Base, свап через Uniswap V3).
"""

import requests
import config


def get_prices():
    """Возвращает (btc_price, eth_price) в USD. При ошибке — (None, None)."""
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbols": '["BTCUSDT","ETHUSDT"]'},
            timeout=10,
        )
        resp.raise_for_status()
        data = {row["symbol"]: float(row["price"]) for row in resp.json()}
        return data.get("BTCUSDT"), data.get("ETHUSDT")
    except Exception as e:
        print(f"[WARN] Не удалось получить цены: {e}")
        return None, None


def execute_trade(action: str, avg_sentiment: float, n_headlines: int):
    """
    action: 'BUY' или 'SELL'.

    Сейчас — заглушка. В paper-режиме ничего реально не исполняет,
    только сигнализирует, что "здесь была бы сделка".

    Чтобы подключить реальное исполнение на Base через Uniswap V3:
    1. Подключи свой существующий модуль работы с некастодиальным кошельком
       (тот же, что использовался в EMA/RSI-версии бота).
    2. Здесь вызови его функцию свапа ETH<->USDC с учётом:
       - размера позиции (% от $100 капитала)
       - stop-loss / take-profit уровней
    3. Верни True/False (успех/неуспех) и фактическую цену исполнения.
    """
    if config.MODE == "paper":
        print(f"[PAPER TRADE] {action} | sentiment={avg_sentiment:.3f} | headlines={n_headlines}")
        return True
    else:
        raise NotImplementedError(
            "Live-исполнение ещё не подключено. Впиши сюда свою Uniswap/Base-логику."
        )
