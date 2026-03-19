import logging
from typing import Tuple
from .utxoracle import UTXOracleClient, UTXOracleError
from .multi_rpc_provider import MultiRPCProvider

logger = logging.getLogger("witness.price_oracle")

class InsufficientEntropyError(Exception):
    """Raised when the block window lacks the minimum required transaction entropy."""
    pass

class UTXOracleEngine:
    """
    UTXOracle v9.1 Thermodynamic Consensus Engine.
    Analyzes the distribution of real on-chain UTXO amounts to derive the 
    underlying fiat payment center of mass. Zero reliance on external meta-data.
    """
    def __init__(
        self,
        rpc_urls: list[str],
        window_size: int = 36,
        min_entropy: int = 10000,
        max_expansion: int = 144
    ):
        self.provider = MultiRPCProvider(rpc_urls)
        self.base_window = window_size
        self.min_entropy = min_entropy
        self.max_expansion = max_expansion
        
        # Instantiate the core UTXOracle client (12-step thermodynamic algorithm)
        # The MultiRPCProvider implements the interface required by the core client.
        self.core_utxo_client = UTXOracleClient(rpc_client=self.provider)

    async def get_price_for_consensus(self, current_height: int) -> Tuple[int, int]:
        """
        Derives the thermodynamic consensus price over a sliding window.
        Automatically expands the window into the past if entropy (L1 TX count) is insufficient.
        Returns: (price_cents_uint64, blocks_scanned)
        """
        logger.info(f"🔬 Executing thermodynamic analysis (Target: {self.base_window} blocks from {current_height})...")
        
        blocks_scanned = self.base_window
        
        while blocks_scanned <= self.max_expansion:
            start_height = current_height - blocks_scanned + 1
            
            try:
                # 1. Entropy Verification
                entropy = await self.core_utxo_client.count_eligible_transactions(start_height, current_height)
                
                if entropy >= self.min_entropy:
                    logger.info(f"🔋 Threshold met: {entropy} transactions across {blocks_scanned} blocks.")
                    
                    # 2. Execution of the 12-step UTXOracle algorithm
                    price_usd = await self.core_utxo_client.compute_price(start_height, current_height)
                    
                    # 3. Final conversion to strict uint64 (USD cents)
                    price_cents_uint64 = int(price_usd * 100)
                    
                    logger.info(f"✅ Consensus Price Validated: {price_cents_uint64} USD cents.")
                    return price_cents_uint64, blocks_scanned
                
                else:
                    logger.warning(f"Low entropy ({entropy}/{self.min_entropy}). Expanding search window (+6 blocks)...")
                    blocks_scanned += 6
                    
            except (UTXOracleError, Exception) as e:
                logger.error(f"UTXOracle extraction error: {e}")
                raise

        raise InsufficientEntropyError(
            f"Failed to reach entropy threshold ({self.min_entropy}) "
            f"after {self.max_expansion} blocks. Market may be illiquid or under attack."
        )

    async def close(self):
        """Gracefully closes the RPC provider connections."""
        await self.provider.close()
