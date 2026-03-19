import asyncio
import logging
import os
from dotenv import load_dotenv

from skills.witness_asset_oracle.multi_rpc_provider import MultiRPCProvider
from skills.witness_asset_oracle.marketplace_fingerprint import PublicRpcAssetDecoder, MarketplaceHeuristicParser

async def audit_trades():
    load_dotenv()
    rpc_urls = os.getenv("BITCOIN_RPC_URLS", "https://bitcoin-rpc.publicnode.com").split(",")
    rpc = MultiRPCProvider(rpc_urls)
    
    decoder = PublicRpcAssetDecoder(rpc)
    parser = MarketplaceHeuristicParser(decoder)
    
    # Historical Trades to Verify
    tests = [
        {"name": "ORDI (BRC-20)", "txid": "dd8504bebc9abedc83647b4edb2a500964f42c0f7e0d47b48f0cda7b455f32b6", "ticker": "ORDI"},
        {"name": "Satflow DOG Sale #1", "txid": "f2f1ca67286e8bb479889cae30d8422c39f15d3421362569749cefb5f6659570", "ticker": "DOG\u2022GO\u2022TO\u2022THE\u2022MOON"},
        {"name": "Satflow DOG Sale #2", "txid": "0b75364518ac422a7aa7cbfaec02eaf8cee54be71e0fa25702f06103af3d5ba8", "ticker": "DOG\u2022GO\u2022TO\u2022THE\u2022MOON"}
    ]
    
    print("\n🧐 Starting High-Fidelity Historical Audit...")
    print("=========================================================")
    
    for test in tests:
        print(f"🔍 Auditing {test['name']} [{test['txid'][:10]}...]")
        try:
            # 1. Fetch the transaction
            tx = await rpc.getrawtransaction(test['txid'], verbose=True)
            if not tx:
                print(f"❌ Could not fetch TX {test['txid']}")
                continue
            
            # 2. Prefetch parent transactions to populate the decoder cache (crucial for address resolution)
            parent_txids = [vin["txid"] for vin in tx.get("vin", []) if "txid" in vin]
            if parent_txids:
                await decoder.prefetch_transactions(list(set(parent_txids)))
                
            # 3. Perform Heuristic Extraction
            trades = await parser.extract_trades_from_tx(tx, test['ticker'])
            
            if trades:
                for t in trades:
                    print(f"✅ SUCCESS: Detected {t.asset_ticker} {t.asset_amount} for {t.sats_paid} sats.")
                    print(f"   - Seller: {t.seller_address[:20]}...")
                    print(f"   - Buyer:  {t.buyer_address[:20]}...")
            else:
                print(f"❌ FAIL: No trade detected for {test['ticker']} in this transaction.")
                
        except Exception as e:
            print(f"❌ Error auditing {test['name']}: {e}")
            
    print("=========================================================")
    await rpc.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(audit_trades())
