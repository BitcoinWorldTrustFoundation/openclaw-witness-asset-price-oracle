import asyncio
import logging
import sys
import os
import binascii

# Add the project root to sys.path
sys.path.append(os.getcwd())

from skills.witness_asset_oracle.logic import AssetOracleLogic
from skills.witness_asset_oracle.config import load_config

async def dump_witness_data():
    config = load_config()
    config.telegram_enabled = False
    logic = AssetOracleLogic(config)
    
    height = 940971
    print(f"🕵️ DEBUGGING BLOCK {height}...")
    
    try:
        block_hash = await logic.provider.getblockhash(height)
        block = await logic.provider.getblock(block_hash, 2)
        
        potential_txs = [tx for tx in block.get("tx", []) if isinstance(tx, dict) and logic.engine.parser._is_market_maker_signature(tx)]
        
        for tx in potential_txs:
            for vin in tx.get("vin", []):
                if logic.engine.parser._is_input_market_maker(vin):
                    parent_txid = vin.get("txid")
                    print(f"\nTXID: {tx['txid']}")
                    print(f"Parent: {parent_txid}")
                    
                    parent_tx = await logic.provider.getrawtransaction(parent_txid, 2)
                    for pvin in parent_tx.get("vin", []):
                        for witness in pvin.get("txinwitness", []):
                            try:
                                decoded = binascii.unhexlify(witness).decode('utf-8', errors='ignore')
                                if '"p":"brc-20"' in decoded:
                                    print(f"  FOUND BRC-20 JSON: {decoded}")
                            except: continue

    except Exception as e:
        print(f"Error: {e}")
            
    await logic.stop()

if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    asyncio.run(dump_witness_data())
