import logging
import math
from typing import List, Optional
from .marketplace_fingerprint import MarketplaceHeuristicParser, TradeFingerprint

logger = logging.getLogger("witness.asset_oracle")

class IlliquidAssetError(Exception):
    """Raised when an asset lacks sufficient trading volume or unique traders."""
    pass

class HighVolatilityWarning(Exception):
    """Raised when the volatility circuit breaker is triggered."""
    pass

class AssetOracleEngine:
    """
    Stateless Bitcoin L1 Price Oracle Engine.
    Exclusively uses on-chain data to derive consensus prices for BRC-20 and Runes.
    Implements advanced safeguards including Volatility Circuit Breakers and Time-Decay recovery.
    """
    def __init__(self, rpc_provider):
        self.rpc = rpc_provider
        from .marketplace_fingerprint import PublicRpcAssetDecoder
        self.decoder = PublicRpcAssetDecoder(rpc_provider)
        self.parser = MarketplaceHeuristicParser(self.decoder)
        
        # Security Parameters (Witness v5.2 Strict)
        self.WINDOW_BLOCKS = 144              # 24h window to mitigate wash trading
        self.MAX_BLOCK_VOLATILITY = 0.15      # 15% maximum allowed price deviation per block
        self.MAX_FREEZE_BLOCKS = 6            # Force update after ~1 hour of extreme volatility
        self.MIN_LIQUIDITY_SATS = 50_000_000  # Minimum 0.5 BTC volume required per window
        self.MIN_UNIQUE_TRADERS = 10          # Minimum unique addresses to prevent sybil/wash trading
        
        self.last_valid_price_sats = None
        self.blocks_since_last_update = 0     # Counter for Time-Decay mechanism

    def enforce_volatility_circuit_breaker(self, current_median_sats: float) -> float:
        """
        Applies a volatility circuit breaker to stabilize the price feed.
        If the price deviates beyond the threshold, it is frozen unless the 
        Time-Decay period (MAX_FREEZE_BLOCKS) has elapsed.
        """
        if self.last_valid_price_sats is None:
            self.last_valid_price_sats = current_median_sats
            self.blocks_since_last_update = 0
            return current_median_sats

        # Calculate percentage deviation from the last confirmed price
        deviation = abs(current_median_sats - self.last_valid_price_sats) / self.last_valid_price_sats

        if deviation > self.MAX_BLOCK_VOLATILITY:
            self.blocks_since_last_update += 1
            
            # Time-Decay: Accept the new price if the market has consolidated the move over time
            if self.blocks_since_last_update >= self.MAX_FREEZE_BLOCKS:
                logger.warning(f"Time-Decay elapsed ({self.MAX_FREEZE_BLOCKS} blocks). "
                               f"Market consolidation confirmed. Accepting new L1 price level.")
                self.last_valid_price_sats = current_median_sats
                self.blocks_since_last_update = 0
                return current_median_sats
            else:
                logger.error(f"Extreme Volatility Detected ({deviation*100:.2f}%). "
                             f"Price frozen. Blocks remaining in freeze: {self.MAX_FREEZE_BLOCKS - self.blocks_since_last_update}")
                raise HighVolatilityWarning(f"Extreme volatility ({deviation*100:.2f}%) triggered circuit breaker.")
        
        # Normal update: price is within stability bounds
        self.last_valid_price_sats = current_median_sats
        self.blocks_since_last_update = 0
        return current_median_sats

    async def _fetch_trades_for_window(self, target_ticker: str, current_height: int) -> List[TradeFingerprint]:
        """Scans the block window using batched RPC calls for optimal performance."""
        all_trades = []
        self.decoder.clear_cache()

        start_height = current_height - self.WINDOW_BLOCKS + 1
        for height in range(start_height, current_height + 1):
            try:
                block_hash = await self.rpc.getblockhash(height)
                block = await self.rpc.getblock(block_hash, 2)
                
                # Identify potential parent transactions for batch prefetching
                potential_parents = []
                for tx in block.get("tx", []):
                    if self.parser._is_market_maker_signature(tx):
                        for vin in tx.get("vin", []):
                            if "txid" in vin: potential_parents.append(vin["txid"])
                
                if potential_parents:
                    await self.decoder.prefetch_transactions(list(set(potential_parents)))

                # Perform trade extraction (leverages the warm cache)
                for tx in block.get("tx",[]):
                    trades = await self.parser.extract_trades_from_tx(tx, target_ticker)
                    all_trades.extend(trades)
            except Exception as e:
                logger.error(f"RPC Error at block {height}: {e}")
        return all_trades

    def _calculate_volume_weighted_median(self, trades: List[TradeFingerprint]) -> float:
        """Derives the median price based on trade volume to resist price manipulation."""
        priced_trades = []
        total_volume_sats = 0
        
        for t in trades:
            price_per_unit = t.sats_paid / t.asset_amount
            priced_trades.append((price_per_unit, t.sats_paid))
            total_volume_sats += t.sats_paid

        # Sort by unit price
        priced_trades.sort(key=lambda x: x[0])

        cumulative_volume = 0
        target_volume = total_volume_sats / 2.0

        for price, vol in priced_trades:
            cumulative_volume += vol
            if cumulative_volume >= target_volume:
                return price
                
        return priced_trades[-1][0] if priced_trades else 0.0

    async def extract_asset_price(self, target_ticker: str, btc_price_cents: int) -> int:
        """
        Main entry point for asset pricing. 
        Returns the consensus price in USD cents (uint64).
        """
        current_height = await self.rpc.getblockcount()
        trades = await self._fetch_trades_for_window(target_ticker, current_height)
        
        if not trades:
            self.blocks_since_last_update += 1
            raise IlliquidAssetError(f"No on-chain trades found for {target_ticker}.")

        # 1. Liquidity Guard (Anti-Manipulation)
        total_volume = sum(t.sats_paid for t in trades)
        unique_traders = set(t.seller_address for t in trades) | set(t.buyer_address for t in trades)

        if total_volume < self.MIN_LIQUIDITY_SATS or len(unique_traders) < self.MIN_UNIQUE_TRADERS:
            self.blocks_since_last_update += 1
            raise IlliquidAssetError(f"Insufficient liquidity (Volume: {total_volume} sats, Traders: {len(unique_traders)}).")

        # 2. Outlier Filtering (Fat-finger protection)
        prices = sorted([t.sats_paid / t.asset_amount for t in trades])
        rough_median = prices[len(prices)//2]
        
        # Reject prices that deviate by more than an order of magnitude from the rough median
        filtered_trades = [
            t for t in trades 
            if rough_median * 0.1 <= (t.sats_paid / t.asset_amount) <= rough_median * 10
        ]

        # 3. Volume-Weighted Median Calculation
        median_price_sats = self._calculate_volume_weighted_median(filtered_trades)

        # 4. Volatility Protection with Time-Decay
        median_price_sats = self.enforce_volatility_circuit_breaker(median_price_sats)

        # 5. Conversion to USD Cents
        token_price_cents = (median_price_sats / 10**8) * btc_price_cents
        
        logger.info(f"Consensus price for {target_ticker}: {token_price_cents:.0f} USD cents.")
        return int(math.floor(token_price_cents))
