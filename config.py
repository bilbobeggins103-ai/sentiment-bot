"""
Конфигурация sentiment-бота.
Все "магические числа" стратегии живут здесь - крути их без изменения логики.
"""

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://cryptoslate.com/feed/",
]

POLL_INTERVAL_SECONDS = 90

RELEVANT_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
    "defi", "nft", "altcoin", "stablecoin", "usdt", "usdc",
    "blockchain", "web3", "token", "coin", "exchange", "wallet",
    "solana", "sol", "xrp", "binance", "coinbase", "sec",
    "mining", "miner", "halving", "staking", "airdrop", "ico",
    "uniswap", "onchain", "on-chain", "layer 2", "l2",
]

BUY_THRESHOLD = 0.25
SELL_THRESHOLD = -0.25
MIN_HEADLINES_FOR_SIGNAL = 3

SENTIMENT_WINDOW_MINUTES = 30
TRADE_COOLDOWN_SECONDS = 20 * 60

SEEN_ITEMS_FILE = "seen_items.json"
RECENT_SCORES_FILE = "recent_scores.json"
LAST_TRADE_FILE = "last_trade.json"
SENTIMENT_LOG_FILE = "sentiment_log.csv"
TRADE_LOG_FILE = "trade_log.csv"

MODE = "paper"
