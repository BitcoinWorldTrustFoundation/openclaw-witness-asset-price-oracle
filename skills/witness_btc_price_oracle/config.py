import os
from dataclasses import dataclass
from typing import List
from dotenv import load_dotenv

@dataclass
class PriceOracleConfig:
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_enabled: bool = False
    
    mempool_api_base: str = "https://mempool.space/api"
    poll_interval_sec: int = 30
    
    price_window_blocks: int = 36
    min_sample_entropy: int = 10000
    max_expansion_blocks: int = 72
    
    bitcoin_rpc_urls: List[str] = None
    binohash_difficulty: int = 2

def load_config(env_file=".env"):
    if os.path.exists(env_file):
        load_dotenv(env_file)
    
    # Load comma separated list of RPC URLs
    urls_str = os.getenv("BITCOIN_RPC_URLS", "https://rpc.ankr.com/bitcoin")
    urls = [u.strip() for u in urls_str.split(",") if u.strip()]
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    
    # Safety: Disable Telegram if placeholders are still present from .env.example
    if "YOUR_BOT_TOKEN" in bot_token or "YOUR_CHAT_ID" in chat_id:
        enabled = False
    
    return PriceOracleConfig(
        telegram_bot_token=bot_token,
        telegram_chat_id=chat_id,
        telegram_enabled=enabled,
        
        mempool_api_base=os.getenv("MEMPOOL_API_BASE", "https://mempool.space/api").rstrip("/"),
        poll_interval_sec=int(os.getenv("POLL_INTERVAL_SEC", "30")),
        
        price_window_blocks=int(os.getenv("PRICE_WINDOW_BLOCKS", "36")),
        min_sample_entropy=int(os.getenv("MIN_SAMPLE_ENTROPY", "10000")),
        max_expansion_blocks=int(os.getenv("MAX_EXPANSION_BLOCKS", "72")),
        
        bitcoin_rpc_urls=urls,
        binohash_difficulty=int(os.getenv("BINOHASH_DIFFICULTY", "2"))
    )
