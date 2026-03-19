import asyncio
import httpx
import logging
from typing import List, Dict, Optional, Any
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger("witness.rpc_provider")

class MultiRPCProvider:
    """
    Robust Multi-RPC Provider for Bitcoin L1.
    Implements JSON-RPC Batching, Load Balancing, and Automatic Failover.
    Ensures high availability even when using public nodes with strict rate limits.
    """
    def __init__(self, rpc_urls: List[str]):
        if not rpc_urls:
            raise ValueError("At least one RPC URL is required.")
        self.rpc_urls = rpc_urls
        self.current_idx = 0
        self.client = httpx.AsyncClient(timeout=30.0)

    async def _call(self, method: str, params: List[Any]) -> Any:
        """Internal helper to execute a single JSON-RPC call with retry and failover."""
        return await self._execute_json_rpc(method, params)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _execute_json_rpc(self, method: str, params: List[Any]) -> Any:
        url = self.rpc_urls[self.current_idx]
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        
        try:
            response = await self.client.post(url, json=payload)
            if response.status_code == 429:
                logger.warning(f"Rate limited (429) on {url}. Switching to next provider.")
                self.current_idx = (self.current_idx + 1) % len(self.rpc_urls)
                raise httpx.HTTPStatusError("Rate limit exceeded", request=response.request, response=response)
                
            response.raise_for_status()
            result = response.json()
            
            if "error" in result and result["error"]:
                raise Exception(f"RPC Error: {result['error']}")
                
            return result.get("result")
            
        except (httpx.HTTPError, Exception) as e:
            logger.error(f"RPC Call Failed [{url}]: {e}")
            self.current_idx = (self.current_idx + 1) % len(self.rpc_urls)
            raise

    async def batch_getrawtransactions(self, txids: List[str]) -> Dict[str, Dict]:
        """
        Fetches multiple raw transactions in a single JSON-RPC batch request.
        Significantly reduces HTTP overhead and bypasses simple rate limit triggers.
        """
        if not txids:
            return {}
            
        url = self.rpc_urls[self.current_idx]
        payload = [
            {"jsonrpc": "2.0", "id": i, "method": "getrawtransaction", "params": [txid, True]}
            for i, txid in enumerate(txids)
        ]
        
        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            results = response.json()
            
            tx_map = {}
            for res in results:
                if "result" in res and res["result"]:
                    txid = res["result"].get("txid")
                    if txid:
                        tx_map[txid] = res["result"]
            return tx_map
            
        except Exception as e:
            logger.error(f"JSON-RPC Batch failed on {url}: {e}")
            # Individual fallback on batch failure
            fallback_results = {}
            for txid in txids:
                try:
                    tx = await self.getrawtransaction(txid, verbose=True)
                    if tx: fallback_results[txid] = tx
                except:
                    continue
            return fallback_results

    async def getblockcount(self) -> int:
        """Returns the current block height."""
        return await self._call("getblockcount", [])

    async def getblockhash(self, height: int) -> str:
        """Returns the hash of the block at the specified height."""
        return await self._call("getblockhash", [height])

    async def getblock(self, blockhash: str, verbosity: int = 2) -> Dict:
        """Returns block data for the specified hash."""
        return await self._call("getblock", [blockhash, verbosity])

    async def getblock_raw(self, blockhash: str) -> bytes:
        """Fetch raw block bytes via RPC verbosity=0."""
        import binascii
        hex_data = await self._call("getblock", [blockhash, 0])
        return binascii.unhexlify(hex_data)

    async def getrawtransaction(self, txid: str, verbose: bool = True) -> Dict:
        """Returns raw transaction data for the specified TXID."""
        return await self._call("getrawtransaction", [txid, verbose])

    async def close(self):
        """Closes the underlying HTTP client."""
        await self.client.aclose()
