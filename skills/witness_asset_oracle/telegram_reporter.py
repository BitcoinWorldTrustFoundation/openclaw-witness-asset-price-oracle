import httpx
import logging
from typing import List, Dict

logger = logging.getLogger("witness.telegram")

class TelegramReporter:
    """
    Witness Telegram Reporter for Global L1 Block Scans.
    Formats and broadcasts Top 5 rankings for BRC-20 and Runes assets.
    """
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    async def broadcast_top_assets(self, block_height: int, btc_price_usd: float, top_brc20: List[Dict], top_runes: List[Dict]):
        """
        Formats and broadcasts the block scan report to the designated Telegram chat.
        """
        if not self.bot_token or not self.chat_id:
            logger.warning("TelegramReporter: Missing bot credentials, broadcast aborted.")
            return

        msg = f"🧊 <b>PRECOP L1 Block Scan: {block_height}</b>\n"
        msg += f"💰 BTC Price: ${btc_price_usd:,.2f}\n\n"

        msg += "🔥 <b>Top 5 BRC-20 (by volume):</b>\n"
        if not top_brc20:
            msg += "<i>No marketplace activity detected.</i>\n"
        else:
            for i, asset in enumerate(top_brc20, 1):
                msg += f"{i}. <b>{asset['ticker']}</b>: ${asset['price_usd']:.6f} (Vol: {asset['volume_btc']:.2f} BTC)\n"

        msg += "\n💎 <b>Top 5 Runes (by volume):</b>\n"
        if not top_runes:
            msg += "<i>No marketplace activity detected.</i>\n"
        else:
            for i, rune in enumerate(top_runes, 1):
                msg += f"{i}. <b>{rune['ticker']}</b>: ${rune['price_usd']:.6f} (Vol: {rune['volume_btc']:.2f} BTC)\n"

        msg += "\n⚡️ <i>Trustless extraction. Zero API. Pure L1 Math.</i>"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.api_url, json={
                    "chat_id": self.chat_id,
                    "text": msg,
                    "parse_mode": "HTML"
                })
                response.raise_for_status()
            logger.info(f"Telegram report successfully broadcasted for block {block_height}")
        except Exception as e:
            logger.error(f"Failed to broadcast Telegram report: {e}")
