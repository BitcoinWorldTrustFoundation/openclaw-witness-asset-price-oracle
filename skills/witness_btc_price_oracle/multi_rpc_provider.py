import asyncio
import logging
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import httpx

logger = logging.getLogger("witness.rpc")

@dataclass
class RPCNode:
    """Represents a Bitcoin RPC endpoint with health tracking."""
    url: str
    failures: int = 0
    last_success: float = 0.0

class MultiRPCProvider:
    """
    Professional Multi-RPC Provider for Bitcoin Mainnet.
    Features smart node rotation, automatic retry logic, and a robust circuit breaker.
    Optimized for high-availability extraction in the Witness ecosystem.
    """
    def __init__(self, rpc_urls: List[str], max_failures: int = 3, cooldown_seconds: int = 30):
        self.nodes: List[RPCNode] = [RPCNode(url=url.strip()) for url in rpc_urls if url.strip()]
        self.max_failures = max_failures
        self.cooldown_seconds = cooldown_seconds
        self.current_index = 0
        self.clients: Dict[str, httpx.AsyncClient] = {
            node.url: httpx.AsyncClient(timeout=15.0) for node in self.nodes
        }

    async def call(self, method: str, params: Optional[List] = None) -> Any:
        """Executes a JSON-RPC call with smart node rotation and retry logic."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}

        # Attempt to reach nodes until a success or exhausted attempts
        for _ in range(len(self.nodes) * 2):
            node = self.nodes[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.nodes)

            # Circuit Breaker: Skip node if it has failed too many times within the cooldown period
            if node.failures >= self.max_failures:
                if time.time() - node.last_success < self.cooldown_seconds:
                    logger.debug(f"Circuit Breaker: Skipping node {node.url} (cooling down)")
                    continue

            client = self.clients[node.url]

            try:
                response = await client.post(node.url, json=payload)
                response.raise_for_status()
                result = response.json()

                if "error" in result and result["error"]:
                    raise Exception(f"RPC Error result: {result['error']}")

                # Reset circuit breaker on success
                node.failures = 0
                node.last_success = time.time()
                return result.get("result")

            except Exception as e:
                node.failures += 1
                logger.warning(f"RPC Fail [{node.url}]: {e} | Failures: {node.failures}/{self.max_failures}")
                continue

        raise Exception("Fatal Error: All configured RPC providers failed after exhaustion and rotation.")

    # Bitcoin Core JSON-RPC Interface
    async def getblockcount(self) -> int:
        return await self.call("getblockcount")

    async def getblockhash(self, height: int) -> str:
        return await self.call("getblockhash", [height])

    async def getblock(self, block_hash: str, verbosity: int = 2) -> Any:
        return await self.call("getblock", [block_hash, verbosity])

    async def getblockheader(self, block_hash: str, verbose: bool = True) -> Any:
        return await self.call("getblockheader", [block_hash, verbose])

    async def getblock_raw(self, block_hash: str) -> bytes:
        """Fetch raw block bytes via RPC verbosity=0."""
        import binascii
        hex_data = await self.call("getblock", [block_hash, 0])
        return binascii.unhexlify(hex_data)

    async def close(self):
        """Gracefully terminates all active HTTP client connections."""
        for client in self.clients.values():
            await client.aclose()
        logger.info("All Multi-RPC client connections closed.")
