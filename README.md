# Sentiment Trading Bot — с нуля

Полностью на sentiment-анализе новостей. Технический анализ (EMA/RSI) убран.

## Структура

```
sentiment-bot/
├── config.py           # все настройки: фиды, пороги, cooldown
├── crypto_lexicon.py    # крипто-жаргон для VADER (moon, rekt, FUD, ...)
├── sentiment_engine.py  # тянет RSS, считает sentiment, хранит "уже виденные" новости
├── decision_engine.py   # превращает sentiment в BUY/SELL/HOLD
├── trader.py            # получение цен BTC/ETH + заглушка исполнения сделки
├── main.py              # главный цикл (запускать этот файл)
├── requirements.txt
└── README.md
```

## Установка (Windows)

```powershell
cd "C:\BZ\trading bot\base-trading-bot"
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Запуск

```powershell
python main.py
```

Бот будет:
1. Каждые `POLL_INTERVAL_SECONDS` (сейчас 90 сек) опрашивать RSS-фиды
2. Считать sentiment новых заголовков (VADER + крипто-словарь)
3. Каждый цикл писать строку в `sentiment_log.csv` (как раньше делала daily-задача,
   только теперь **постоянно**, а не раз в день)
4. Если средний sentiment за последние 30 минут выходит за пороги — логировать
   сигнал BUY/SELL в `trade_log.csv`

Сейчас режим `paper` (`config.MODE = "paper"`) — сделки только логируются, реально
ничего не исполняется. Когда будешь готов — переключишь на `live` и допишешь
в `trader.py` вызов своей Uniswap/Base-логики (кошелёк, свап, размер позиции).

## Про старую задачу CryptoSentimentDaily

Раньше был Scheduled Task, который раз в день в 9:00 запускал скрипт и завершался.
Теперь `main.py` — это **постоянно работающий процесс** (real-time реакция на новости),
а не разовая задача. Поэтому вместо `CryptoSentimentDaily` его стоит:

- либо просто оставлять запущенным в окне PowerShell/терминала,
- либо (надёжнее) настроить как Windows-службу через **NSSM** (Non-Sucking Service
  Manager), чтобы он не зависел от открытой сессии и переживал перезагрузки.

Могу помочь настроить NSSM отдельно, если нужно.

## Настройка порогов

Все ключевые числа — в `config.py`:

- `BUY_THRESHOLD` / `SELL_THRESHOLD` — пороги среднего sentiment
- `MIN_HEADLINES_FOR_SIGNAL` — минимум новостей в окне для валидного сигнала
- `SENTIMENT_WINDOW_MINUTES` — окно агрегации
- `TRADE_COOLDOWN_SECONDS` — минимальный интервал между сделками
- `RSS_FEEDS` — список источников (можно добавлять свои)

Стартовые значения — предположение, не проверенное на истории. Следующий
логичный шаг — прогнать бэктест на архивных новостях (например, экспорт
из CryptoPanic API или своей собранной базы), чтобы подобрать пороги осмысленно,
а не на глаз.
