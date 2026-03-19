import asyncio
import logging
import os
from dotenv import load_dotenv

from skills.witness_asset_oracle.multi_rpc_provider import MultiRPCProvider
from skills.witness_asset_oracle.marketplace_fingerprint import PublicRpcAssetDecoder, MarketplaceHeuristicParser
from skills.witness_asset_oracle.telegram_reporter import TelegramReporter

async def rescan_block(height: int):
    load_dotenv()
    
    # 1. Setup Providers
    rpc_urls = os.getenv("BITCOIN_RPC_URLS", "https://bitcoin-rpc.publicnode.com").split(",")
    rpc = MultiRPCProvider(rpc_urls)
    
    decoder = PublicRpcAssetDecoder(rpc)
    parser = MarketplaceHeuristicParser(decoder)
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    reporter = TelegramReporter(bot_token, chat_id)
    btc_price_usd = 69430.94 # Fixed benchmark for the rescan
    
    print(f"📡 Rescanning Block {height} with Dynamic Scanner...")
    
    try:
        # 2. Fetch Block data (verbosity=2)
        block_hash = await rpc.getblockhash(height)
        block = await rpc.getblock(block_hash, 2)
        
        # 3. Discover Trades Dynamically
        trades = await parser.discover_trades_in_block(block)
        
        # 4. Aggregation Logic (from logic.py)
        top_brc20 = []
        top_runes = []
        btc_price_cents = int(btc_price_usd * 100)

        if trades:
            brc20_data = {}
            runes_data = {}
            
            for t in trades:
                if t.asset_amount <= 0: continue
                vol_btc = t.sats_paid / 10**8
                price_usd = (t.sats_paid / t.asset_amount) * (btc_price_cents / 10**8)
                
                is_rune = t.asset_ticker == "RUNES" or "•" in t.asset_ticker or len(t.asset_ticker) > 5
                target_dict = runes_data if is_rune else brc20_data
                
                if t.asset_ticker not in target_dict:
                    target_dict[t.asset_ticker] = {"volume_btc": 0, "price_usd": price_usd}
                target_dict[t.asset_ticker]["volume_btc"] += vol_btc
            
            top_brc20 = sorted([{"ticker": k, **v} for k, v in brc20_data.items()], key=lambda x: x["volume_btc"], reverse=True)[:5]
            top_runes = sorted([{"ticker": k, **v} for k, v in runes_data.items()], key=lambda x: x["volume_btc"], reverse=True)[:5]

        # 5. Broadcast
        await reporter.broadcast_top_assets(height, btc_price_usd, top_brc20, top_runes)
        print(f"✅ Report sent to Telegram for block {height}!")
        if trades:
            print(f"🔥 Found {len(trades)} trades.")

    except Exception as e:
        print(f"❌ Rescan failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await rpc.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(rescan_block(941338))
