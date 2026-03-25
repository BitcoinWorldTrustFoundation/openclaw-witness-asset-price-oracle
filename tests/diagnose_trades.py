import asyncio
import logging
import sys
import os
import binascii

# Add the project root to sys.path
sys.path.append(os.getcwd())

from skills.witness_asset_oracle.logic import AssetOracleLogic
from skills.witness_asset_oracle.config import load_config

async def diagnose_trades():
    config = load_config()
    config.telegram_enabled = False
    logic = AssetOracleLogic(config)
    
    test_blocks = [942117, 942083, 940971]
    
    print("🔍 DIAGNOSING TRADES IN TEST BLOCKS...")
    
    for height in test_blocks:
        print(f"\n--- BLOCK {height} ---")
        try:
            block_hash = await logic.provider.getblockhash(height)
            block = await logic.provider.getblock(block_hash, 2)
            
            # Step-by-step discovery logging
            print(f"Total TXs: {len(block['tx'])}")
            
            potential_txs = [tx for tx in block.get("tx", []) if isinstance(tx, dict) and logic.engine.parser._is_market_maker_signature(tx)]
            print(f"Potential Market Maker TXs: {len(potential_txs)}")
            
            trades = await logic.engine.parser.discover_trades_in_block(block)
            print(f"Discovered Trades (pre-aggregation): {len(trades)}")
            
            for t in trades:
                print(f"  FOUND {t.asset_type}: {t.asset_ticker} | Amount: {t.asset_amount} | Paid: {t.sats_paid} sats | TX: {t.txid[:10]}...")
            
            if not trades:
                # If no trades found, let's peek at a few TXs to see if we miss something
                for tx in potential_txs[:5]:
                    print(f"  Checking TX {tx['txid'][:10]} inputs...")
                    for vin in tx.get("vin", []):
                        if logic.engine.parser._is_input_market_maker(vin):
                            print(f"    Maker input found in {tx['txid'][:10]}")
                            # Check parents
                            parent_txid = vin.get("txid")
                            if parent_txid:
                                amt = await logic.engine.parser.decoder.get_brc20_transfer_amount(parent_txid, "ORDI")
                                if amt: print(f"      DETECTED {amt} ORDI in parent!")
                                
                                runes = await logic.engine.parser.decoder.get_runes_transfer_amount(tx)
                                if runes: print(f"      DETECTED {runes} Runes in TX!")

        except Exception as e:
            print(f"Error in diagnosis for block {height}: {e}")
            import traceback
            traceback.print_exc()
            
    await logic.stop()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO) # Enable more info
    asyncio.run(diagnose_trades())
