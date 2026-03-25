import json
import logging
import time
import asyncio
from pathlib import Path
from .multi_rpc_provider import MultiRPCProvider
from .asset_oracle_engine import AssetOracleEngine, IlliquidAssetError, HighVolatilityWarning
from .config import AssetOracleConfig
from .telegram_reporter import TelegramReporter

logger = logging.getLogger("witness.asset_logic")

class AssetOracleLogic:
    """
    Main controller bridging Bitcoin L1 blockchain and the IndexerClaw.
    Manages the asynchronous pricing loop, exceptions, and state persistence.
    Integrated with Telegram for real-time Witness Block Scanning and reporting.
    """
    def __init__(self, config: AssetOracleConfig):
        self.config = config
        self.provider = MultiRPCProvider(config.bitcoin_rpc_urls)
        self.engine = AssetOracleEngine(self.provider)
        self.telegram = None
        if config.telegram_enabled:
            self.telegram = TelegramReporter(config.telegram_bot_token, config.telegram_chat_id)
        self.last_asset_price_cents = 0
        self.last_scanned_block = 0
        self.running = False

    async def _get_btc_price_cents(self) -> int:
        """Retrieves the latest benchmark BTC price from the disk state file."""
        try:
            path = Path(self.config.btc_state_file)
            if path.exists():
                with path.open() as f:
                    data = json.load(f)
                return data.get("price_cents_uint64", 0)
        except Exception as e:
            logger.error(f"Error reading benchmark BTC price: {e}")
        return 0

    def _save_asset_state(self, ticker: str, price_cents: int):
        """Persists the asset price state in the format required by IndexerClaw."""
        state = {
            "ticker": ticker,
            "price_cents_uint64": price_cents,
            "data_age_blocks": 0,
            "timestamp": int(time.time()),
            "source": "Witness_Asset_Oracle_v1"
        }
        
        path = Path(self.config.asset_state_file)
        tmp_path = path.with_suffix(".tmp")
        with tmp_path.open("w") as f:
            json.dump(state, f, indent=2)
        tmp_path.replace(path)
        logger.info(f"✅ State updated for {ticker}: {price_cents} USD cents.")

    async def run(self):
        """Starts the main asynchronous polling loop."""
        self.running = True
        logger.info(f"🚀 Starting Witness Asset Oracle for ticker {self.config.target_ticker}...")
        
        while self.running:
            try:
                # 1. Fetch reference BTC price
                btc_price = await self._get_btc_price_cents()
                if btc_price == 0:
                    logger.warning("Benchmark BTC price unavailable. Waiting for BTC Oracle...")
                    await asyncio.sleep(10)
                    continue

                # 2. Global Block Scanning for Telegram Broadcast (Always prioritized)
                if self.telegram:
                    await self._run_global_scan_if_new_block(btc_price)

                # 3. Extract specific asset price using the heuristic L1 engine
                try:
                    asset_price = await self.engine.extract_asset_price(
                        self.config.target_ticker, 
                        btc_price
                    )
                    # 4. State persistence (only if price extraction succeeds)
                    self._save_asset_state(self.config.target_ticker, asset_price)
                    self.last_asset_price_cents = asset_price
                except IlliquidAssetError as e:
                    logger.warning(f"⚠️ Insufficient trading entropy for {self.config.target_ticker}: {e}")
                except HighVolatilityWarning as e:
                    logger.critical(f"🛑 CIRCUIT BREAKER TRIPPED: {e}")

            except Exception as e:
                logger.error(f"❌ Critical error in Asset Oracle Loop: {e}", exc_info=True)
            
            await asyncio.sleep(self.config.poll_interval_sec)

    async def _run_global_scan_if_new_block(self, btc_price_cents: int):
        """Detects new blocks and triggers a global scan for ranking reports."""
        try:
            current_height = await self.provider.getblockcount()
            if current_height > self.last_scanned_block:
                logger.info(f"🔍 New block {current_height} detected. Initiating global marketplace scan...")
                
                block_hash = await self.provider.getblockhash(current_height)
                block = await self.provider.getblock(block_hash, 2)
                
                # Exhaustive L1 discovery
                trades = await self.engine.parser.discover_trades_in_block(block)
                
                top_brc20 = []
                top_runes = []
                
                if trades:
                    # Categories: {"BRC20": {"TICK": {"vol": 0, "sats": 0, "amount": 0}}, "RUNES": {...}}
                    stats = {"BRC20": {}, "RUNES": {}}
                    
                    for t in trades:
                        if t.asset_amount <= 0: continue
                        
                        target_cat = stats.get(t.asset_type, stats["BRC20"])
                        if t.asset_ticker not in target_cat:
                            target_cat[t.asset_ticker] = {"volume_btc": 0, "sats": 0, "amount": 0}
                        
                        target_cat[t.asset_ticker]["volume_btc"] += t.sats_paid / 10**8
                        target_cat[t.asset_ticker]["sats"] += t.sats_paid
                        target_cat[t.asset_ticker]["amount"] += t.asset_amount
                    
                    # Process Aggregated Data (VWAP and Filtering)
                    # Min volume: 50,000 sats (0.0005 BTC) to avoid dust/spam in report
                    MIN_REPORT_VOL_SATS = 50_000 
                    
                    processed_brc20 = []
                    for ticker, data in stats["BRC20"].items():
                        if data["sats"] < MIN_REPORT_VOL_SATS: continue
                        price_usd = (data["sats"] / data["amount"]) * (btc_price_cents / 100 / 10**8)
                        processed_brc20.append({"ticker": ticker, "volume_btc": data["volume_btc"], "price_usd": price_usd})

                    processed_runes = []
                    for ticker, data in stats["RUNES"].items():
                        if data["sats"] < MIN_REPORT_VOL_SATS: continue
                        price_usd = (data["sats"] / data["amount"]) * (btc_price_cents / 100 / 10**8)
                        processed_runes.append({"ticker": ticker, "volume_btc": data["volume_btc"], "price_usd": price_usd})
                    
                    # Top 5 Rankings by volume
                    top_brc20 = sorted(processed_brc20, key=lambda x: x["volume_btc"], reverse=True)[:5]
                    top_runes = sorted(processed_runes, key=lambda x: x["volume_btc"], reverse=True)[:5]
                
                # Telegram Broadcast
                await self.telegram.broadcast_top_assets(
                    current_height, btc_price_cents / 100, top_brc20, top_runes
                )
                
                self.last_scanned_block = current_height
        except Exception as e:
            logger.error(f"Global Telegram scan error: {e}")

    async def stop(self):
        """Gracefully shuts down the controller."""
        self.running = False
        await self.provider.close()
        logger.info("Asset Oracle Skill stopped.")

def main():
    """Entry point for the Asset Oracle console script."""
    from .config import load_config
    config = load_config()
    logic = AssetOracleLogic(config)
    
    # Simple console logger for the script
    logging.basicConfig(level=logging.INFO)
    
    try:
        asyncio.run(logic.run())
    except KeyboardInterrupt:
        asyncio.run(logic.stop())
