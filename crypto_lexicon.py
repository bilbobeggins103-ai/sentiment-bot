"""
Кастомный крипто-словарь, дополняющий VADER.
VADER из коробки не знает крипто-жаргон ("moon", "rekt", "FUD" и т.д.)
Значения — по шкале VADER: примерно от -4 (максимально негативно) до +4 (максимально позитивно).
"""

CRYPTO_LEXICON = {
    # Бычьи / позитивные термины
    "moon": 3.0,
    "mooning": 3.0,
    "bullish": 2.5,
    "pump": 2.0,
    "pumping": 2.0,
    "ath": 2.5,          # all-time high
    "breakout": 2.0,
    "rally": 2.0,
    "accumulate": 1.5,
    "accumulation": 1.5,
    "hodl": 1.0,
    "adoption": 2.0,
    "partnership": 1.5,
    "upgrade": 1.5,
    "halving": 1.0,
    "institutional": 1.0,
    "staking": 0.8,
    "listing": 1.2,
    "surge": 2.0,
    "rocket": 2.0,

    # Медвежьи / негативные термины
    "dump": -2.0,
    "dumping": -2.0,
    "bearish": -2.5,
    "rekt": -3.0,
    "fud": -2.0,
    "crash": -3.0,
    "crashing": -3.0,
    "rug": -3.5,
    "rugpull": -3.5,
    "hack": -3.0,
    "hacked": -3.0,
    "exploit": -2.5,
    "exploited": -2.5,
    "scam": -3.0,
    "ban": -2.5,
    "banned": -2.5,
    "delist": -2.0,
    "delisting": -2.0,
    "liquidation": -2.5,
    "liquidated": -2.5,
    "selloff": -2.5,
    "sell-off": -2.5,
    "capitulation": -2.5,
    "bankruptcy": -3.0,
    "insolvent": -3.0,
    "insolvency": -3.0,
    "lawsuit": -1.5,
    "sec": -0.5,          # регуляторный контекст обычно нейтрально-негативный
    "regulation": -0.5,
    "crackdown": -2.0,
    "investigation": -1.5,
    "outflow": -1.0,
    "outflows": -1.0,
}
