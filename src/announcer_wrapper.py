import asyncio
import logging
from contextlib import asynccontextmanager
from skills.witness_btc_price_oracle.config import load_config as load_btc_config
from skills.witness_btc_price_oracle.logic import PriceOracleLogic
from skills.witness_asset_oracle.config import load_config as load_asset_config
from skills.witness_asset_oracle.logic import AssetOracleLogic

logger = logging.getLogger("witness")

class WitnessOracleWrapper:
    """Wrapper to run both BTC Price and Asset Witness Oracles gracefully."""
    def __init__(self):
        # Load BTC Pricing Config
        self.btc_config = load_btc_config()
        self.btc_logic = PriceOracleLogic(self.btc_config)
        
        # Load Asset Witness Config
        self.asset_config = load_asset_config()
        self.asset_logic = AssetOracleLogic(self.asset_config)

    async def _lifecycle(self):
        try:
            # Initialize both skills
            await self.btc_logic.setup()
            # Launch both loops concurrently
            await asyncio.gather(
                self.btc_logic.run(),
                self.asset_logic.run()
            )
        except asyncio.CancelledError:
            pass
        finally:
            await asyncio.gather(
                self.btc_logic.stop(),
                self.asset_logic.stop()
            )
            logger.info("Witness Oracle ecosystem shutdown complete.")

    def run_sync(self):
        """Run the oracle ecosystem with a professional unified banner."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)-7s | %(name)-15s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        print("\n" + "="*60)
        print("  🐾 WITNESS ORACLE ECOSYSTEM | THE TRUTH MINER ".center(60))
        print("  Native Bitcoin L1 Price & Asset Intelligence".center(60))
        print("="*60)
        print(f"  > BTC Polling:       {self.btc_config.poll_interval_sec}s")
        print(f"  > Asset Polling:     {self.asset_config.poll_interval_sec}s")
        print(f"  > Binohash Guard:    W={self.btc_config.binohash_difficulty}")
        print(f"  > Status Target:     {self.asset_config.target_ticker}")
        print(f"  > Global Scan:       ALL (BRC-20 + Runes)")
        print("="*60 + "\n")
        
        try:
            asyncio.run(self._lifecycle())
        except KeyboardInterrupt:
            print("\n" + "-"*60)
            print("  🛑 Ecosystem shutdown signal received. Graceful exit...".center(60))
            print("-"*60 + "\n")

def main():
    """Main CLI entry point for the Witness Oracle."""
    wrapper = WitnessOracleWrapper()
    wrapper.run_sync()

if __name__ == "__main__":
    main()
