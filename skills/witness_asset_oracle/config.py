import os
from dataclasses import dataclass
from typing import List
from dotenv import load_dotenv

load_dotenv()

@dataclass
class AssetOracleConfig:
    """Configuration container for the Witness Asset Oracle Engine."""
    poll_interval_sec: int = 60
    target_ticker: str = "ORDI"
    
    # Telegram Configuration
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_enabled: bool = False
    
    # RPC Configuration
    bitcoin_rpc_urls: List[str] = None
    
    # State File Paths
    btc_state_file: str = "btc_price_state.json"
    asset_state_file: str = "asset_price_state.json"

def load_config() -> AssetOracleConfig:
    """
    Loads Asset Oracle configuration from environment variables.
    Provides robust fallbacks for public Bitcoin L1 RPC endpoints.
    """
    rpc_urls_str = os.getenv("BITCOIN_RPC_URLS", "https://rpc.ankr.com/bitcoin")
    rpc_urls = [u.strip() for u in rpc_urls_str.split(",") if u.strip()]
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    is_telegram_enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    
    # Security Guard: Disable Telegram if placeholder credentials remain in environment
    if "YOUR_BOT_TOKEN" in bot_token or "YOUR_CHAT_ID" in chat_id or not bot_token:
        is_telegram_enabled = False
    
    return AssetOracleConfig(
        poll_interval_sec=int(os.getenv("ASSET_POLL_INTERVAL_SEC", "60")),
        target_ticker=os.getenv("TARGET_ASSET_TICKER", "ORDI"),
        telegram_bot_token=bot_token,
        telegram_chat_id=chat_id,
        telegram_enabled=is_telegram_enabled,
        bitcoin_rpc_urls=rpc_urls
    )
