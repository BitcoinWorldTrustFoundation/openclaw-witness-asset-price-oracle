import asyncio
import logging
import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())

from skills.witness_asset_oracle.logic import AssetOracleLogic
from skills.witness_asset_oracle.config import load_config

async def simulate_telegram():
    config = load_config()
    # We WANT telegram enabled for this simulation
    config.telegram_enabled = True
    logic = AssetOracleLogic(config)
    
    # Mock BTC price ($70,000)
    btc_price_cents = 7000000
    
    test_blocks = [942117, 942083, 940971]
    
    print("🚀 Starting Telegram simulation for 3 test blocks...")
    
    for height in test_blocks:
        print(f"\nScanning block {height}...")
        try:
            block_hash = await logic.provider.getblockhash(height)
            block = await logic.provider.getblock(block_hash, 2)
            
            # Use the logic's internal scan function manually
            # This will trigger telegram.broadcast_top_assets
            print(f"Discovering trades for block {height}...")
            trades = await logic.engine.parser.discover_trades_in_block(block)
            
            top_brc20 = []
            top_runes = []
            
            if trades:
                stats = {"BRC20": {}, "RUNES": {}}
                for t in trades:
                    if t.asset_amount <= 0: continue
                    target_cat = stats.get(t.asset_type, stats["BRC20"])
                    if t.asset_ticker not in target_cat:
                        target_cat[t.asset_ticker] = {"volume_btc": 0, "sats": 0, "amount": 0}
                    target_cat[t.asset_ticker]["volume_btc"] += t.sats_paid / 10**8
                    target_cat[t.asset_ticker]["sats"] += t.sats_paid
                    target_cat[t.asset_ticker]["amount"] += t.asset_amount

                MIN_REPORT_VOL_SATS = 50_000 
                
                processed_brc20 = []
                for ticker, data in stats["BRC20"].items():
                    if data["sats"] < MIN_REPORT_VOL_SATS: continue
                    price_usd = (data["sats"] / data["amount"]) * (btc_price_cents / 10**8)
                    processed_brc20.append({"ticker": ticker, "volume_btc": data["volume_btc"], "price_usd": price_usd})

                processed_runes = []
                for ticker, data in stats["RUNES"].items():
                    if data["sats"] < MIN_REPORT_VOL_SATS: continue
                    price_usd = (data["sats"] / data["amount"]) * (btc_price_cents / 10**8)
                    processed_runes.append({"ticker": ticker, "volume_btc": data["volume_btc"], "price_usd": price_usd})
                
                top_brc20 = sorted(processed_brc20, key=lambda x: x["volume_btc"], reverse=True)[:5]
                top_runes = sorted(processed_runes, key=lambda x: x["volume_btc"], reverse=True)[:5]

            print(f"Broadcasting report for block {height}...")
            await logic.telegram.broadcast_top_assets(
                height, btc_price_cents / 100, top_brc20, top_runes
            )
            print(f"✅ Report sent for block {height}")
            
            # Small delay to avoid telegram rate limits
            await asyncio.sleep(2)
            
        except Exception as e:
            print(f"❌ Error in simulation for block {height}: {e}")
            
    await logic.stop()

if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    asyncio.run(simulate_telegram())
