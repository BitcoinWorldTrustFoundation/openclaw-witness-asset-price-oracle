import httpx
import logging
import json
from typing import Dict

logger = logging.getLogger("witness.telegram")


class TelegramAnnouncer:
    def __init__(self, config):
        self.config = config
        self.api_url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
        self.enabled = (
            self.config.telegram_enabled
            and self.config.telegram_bot_token
            and self.config.telegram_chat_id
        )

    async def send_announcement_json(self, state: Dict):
        """Sends full L1 Witness JSON to Telegram with clean formatting."""
        if not self.enabled:
            logger.debug("Telegram announcements disabled or missing config.")
            return

        pretty_json = json.dumps(state, indent=2, ensure_ascii=False)

        text = (
            f"🧡 <b>New Bitcoin Block Mined!</b>\n\n"
            f"<pre>{pretty_json}</pre>\n\n"
            f"Trustless on-chain price feed for PRECOP covenants.\n"
            f"<a href='https://mempool.space/block/{state.get('height')}'>View Block on mempool.space</a>\n"
            f"#Bitcoin #PRECOP #UTXOracle"
        )

        payload = {
            "chat_id": self.config.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(self.api_url, json=payload)
                r.raise_for_status()
            logger.info(f"✅ Telegram JSON announcement sent for block {state.get('height')}")
        except httpx.HTTPStatusError as e:
            logger.error(f"Telegram HTTP error: {e.response.text}")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
