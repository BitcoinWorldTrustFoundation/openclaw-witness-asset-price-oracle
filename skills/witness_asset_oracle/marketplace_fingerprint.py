import json
import binascii
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger("witness.fingerprint")

@dataclass
class TradeFingerprint:
    """Heuristic fingerprint of an identified L1 asset trade."""
    txid: str
    asset_ticker: str
    asset_amount: int
    sats_paid: int
    seller_address: str
    buyer_address: str
    asset_type: str = "BRC20" # BRC20 or RUNES

class VarIntReader:
    """Utility to read LEB128 encoded integers (VarInts) from Bitcoin script data."""
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read_varint(self) -> Optional[int]:
        res = 0
        shift = 0
        while self.pos < len(self.data):
            byte = self.data[self.pos]
            self.pos += 1
            res |= (byte & 0x7f) << shift
            if not (byte & 0x80):
                return res
            shift += 7
        return None

class RuneNameResolver:
    """
    Lazy resolver for Rune names (BIP-13).
    Caches RuneId -> Name mappings to minimize RPC calls.
    Decodes on-chain integers into human-readable Rune names.
    """
    def __init__(self, multi_rpc_provider):
        self.rpc = multi_rpc_provider
        # Hardcoded Protocol Constants
        self.cache: Dict[str, str] = {
            "1:0": "UNCOMMON•GOODS"
        }

    def _decode_rune_name(self, n: int) -> str:
        """Converts a Rune integer (uint128) to its human-readable string (A-Z)."""
        if n == 0: return "A"
        name = ""
        while True:
            name = chr(ord('A') + (n % 26)) + name
            if n < 26: break
            n = (n // 26) - 1
        return name

    async def resolve_name(self, rune_id: str) -> str:
        """Fetch etching transaction from L1 and decode the Rune name."""
        if rune_id in self.cache:
            return self.cache[rune_id]

        try:
            height, tx_idx = map(int, rune_id.split(':'))
            block_hash = await self.rpc.getblockhash(height)
            block = await self.rpc.getblock(block_hash, 1) # Verbosity 1 for TXIDs
            
            if tx_idx >= len(block.get("tx", [])):
                return f"Rune[{rune_id}]"

            etching_txid = block["tx"][tx_idx]
            etching_tx = await self.rpc.getrawtransaction(etching_txid, verbose=True)
            
            # Find the Etching inside the Runestone
            for vout in etching_tx.get("vout", []):
                script_hex = vout.get("scriptPubKey", {}).get("hex", "")
                if script_hex.startswith("6a5d"):
                    payload = binascii.unhexlify(script_hex[6:])
                    reader = VarIntReader(payload)
                    
                    # Tags: 4 is RUNE name
                    while True:
                        tag = reader.read_varint()
                        if tag is None or tag == 0: break
                        val = reader.read_varint()
                        if tag == 4: # Tag 4 is the Rune name integer in an Etching
                            name = self._decode_rune_name(val)
                            self.cache[rune_id] = name
                            return name
        except Exception as e:
            logger.debug(f"Failed to resolve Rune name for {rune_id}: {e}")
        
        return f"Rune[{rune_id}]"

class PublicRpcAssetDecoder:
    """
    Decodes L1 asset data (BRC-20, Runes) by querying raw block data.
    Zero external dependencies on indexers or centralized APIs.
    """
    def __init__(self, multi_rpc_provider):
        self.rpc = multi_rpc_provider
        self.cache: Dict[str, Dict] = {}

    def clear_cache(self):
        """Clears the internal transaction cache."""
        self.cache.clear()

    async def prefetch_transactions(self, txids: List[str]):
        """Fetches transactions in batches to optimize RPC overhead."""
        missing = [txid for txid in txids if txid not in self.cache]
        if not missing:
            return
            
        # Batching by 50 to avoid oversized JSON-RPC payloads
        batch_size = 50
        for i in range(0, len(missing), batch_size):
            batch = missing[i:i+batch_size]
            try:
                results = await self.rpc.batch_getrawtransactions(batch)
                self.cache.update(results)
            except Exception as e:
                logger.error(f"Batch prefetch failed: {e}")

    async def get_brc20_transfer_amount(self, parent_txid: str, target_ticker: str) -> Optional[int]:
        """
        Extracts BRC-20 'transfer' amount from the Parent transaction's witness data.
        """
        try:
            if parent_txid in self.cache:
                parent_tx = self.cache[parent_txid]
            else:
                parent_tx = await self.rpc.getrawtransaction(parent_txid, verbose=True)
                if parent_tx:
                    self.cache[parent_txid] = parent_tx

            if not parent_tx:
                return None
                
            for vin in parent_tx.get("vin",[]):
                witness_data = vin.get("txinwitness",[])
                
                for item in witness_data:
                    try:
                        decoded_ascii = binascii.unhexlify(item).decode('utf-8', errors='ignore')
                        if '"p":"brc-20"' not in decoded_ascii:
                            continue
                            
                        json_start = decoded_ascii.find('{')
                        json_end = decoded_ascii.rfind('}') + 1
                        
                        if json_start != -1 and json_end > json_start:
                            brc20_data = json.loads(decoded_ascii[json_start:json_end])
                            if (brc20_data.get("op") == "transfer" and 
                                brc20_data.get("tick", "").lower() == target_ticker.lower()):
                                return int(brc20_data.get("amt", 0))
                    except (json.JSONDecodeError, ValueError):
                        continue
            return None
        except Exception as e:
            logger.debug(f"BRC-20 decoding error for {parent_txid}: {e}")
            return None

    async def get_runes_transfer_amount(self, tx: Dict) -> List[Tuple[str, int]]:
        """
        Parses a Runestone (OP_RETURN 13) to extract the transferred amounts (BIP-13).
        Returns a list of (rune_id, amount) tuples.
        """
        results = []
        for vout in tx.get("vout", []):
            script_hex = vout.get("scriptPubKey", {}).get("hex", "")
            
            # 6a = OP_RETURN, 5d = OP_13 (Runestone)
            if script_hex.startswith("6a5d"):
                try:
                    payload = binascii.unhexlify(script_hex[6:])
                    reader = VarIntReader(payload)
                    
                    # Parse Runestone Fields (Tags and Values)
                    tags = {}
                    # Tag 30 = MINT (RuneId being minted)
                    # Tag 20 = POINTER (Default destination)
                    while True:
                        tag = reader.read_varint()
                        if tag is None or tag == 0: # 0 = End of Tags / Edicts start
                            break
                        val = reader.read_varint()
                        if val is None: break
                        tags[tag] = val
                        
                        # Handle Mint discovery
                        if tag == 30: # MINT
                            # Mints usually create a batch (total supply depends on Rune definition)
                            # For discovery, we can't know the amount without the Rune definition, 
                            # but we can return the ID.
                            # Resolve Mint ID from tags (Block:Tx)
                            # Wait! Tag 30 is the block, next is Tx? No, Tag 30 is block, Tag 31 is Tx.
                            pass
                    
                    if 30 in tags:
                        block_height = tags[30]
                        tx_idx = tags.get(31, 0)
                        results.append((f"{block_height}:{tx_idx}", 0)) # Amount 0 for now
                    
                    # Tag 7 = EDICTS (The actual transfers)
                    # Every edict is a block, tx, amount, output tuple (4 VarInts, Delta encoded)
                    block_acc = 0
                    tx_acc = 0
                    while True:
                        block_delta = reader.read_varint()
                        if block_delta is None: break
                        
                        tx_delta = reader.read_varint()
                        amount = reader.read_varint()
                        output = reader.read_varint()
                        
                        if block_delta == 0:
                            tx_acc += tx_delta
                        else:
                            block_acc += block_delta
                            tx_acc = tx_delta
                            
                        if amount:
                            rune_id = f"{block_acc}:{tx_acc}"
                            results.append((rune_id, amount))
                except Exception as e:
                    logger.error(f"Runestone parsing error: {e}")
            
            # Check for non-standard marketplace markers (e.g. SATFLOW)
            elif "534154464c4f57" in script_hex: # "SATFLOW"
                # This transaction is a market trade but doesn't have a Runestone.
                # It relies on default moves of Runes in inputs. 
                # We return a special marker to trigger parent analysis.
                results.append(("DEFAULT", 0))

        return list(set(results))

class MarketplaceHeuristicParser:
    """
    Analyzes Bitcoin transactions (PSBT-style) to identify marketplace trades.
    Supports Taproot (BIP-341/342) and SegWit v0 signatures.
    """
    def __init__(self, decoder: PublicRpcAssetDecoder):
        self.decoder = decoder
        self.rune_resolver = RuneNameResolver(decoder.rpc)

    def _is_market_maker_signature(self, tx: Dict) -> bool:
        """Determines if a transaction contains a Seller (Maker) signature via SIGHASH flags."""
        for vin in tx.get("vin",[]):
            if self._is_input_market_maker(vin):
                return True
        return False

    def _is_input_market_maker(self, vin: Dict) -> bool:
        """Determines if a specific input contains a Seller signature (SIGHASH_SINGLE)."""
        witness = vin.get("txinwitness", [])
        if not witness:
            return False
        # Check both the first item (Signature) and last item (Fallback)
        for item in [witness[0], witness[-1]]:
            if item.endswith("83") or item.endswith("03"):
                # Taproot/Schnorr signature hardening: must be ~130 hex chars (65 bytes)
                if item.endswith("03") and len(item) not in [128, 130]:
                    continue 
                return True
        return False

    async def extract_trades_from_tx(self, tx: Dict, target_ticker: str, asset_type: str = "BRC20") -> List[TradeFingerprint]:
        """Identifies trade fingerprints by matching asset transfers with BTC payments."""
        if not self._is_market_maker_signature(tx):
            return []

        seller_inputs = []
        is_runes = (asset_type == "RUNES")
        
        for i, vin in enumerate(tx.get("vin",[])):
            if "txid" not in vin: continue
            
            # THE HEURISTIC: The seller is the one providing the marketplace signature (SIGHASH_SINGLE)
            if not self._is_input_market_maker(vin):
                continue
                
            if is_runes:
                runes_transfers = await self.decoder.get_runes_transfer_amount(tx)
                
                # Case A: Implicit default moves (e.g. SATFLOW or simple Pointer)
                if not runes_transfers or any(r[0] == "DEFAULT" for r in runes_transfers):
                    # We must check what Runes the maker input had in its parent
                    parent_runes = await self._discover_runes_from_inputs(tx)
                    for rid, amt in parent_runes:
                        if target_ticker in ["RUNES", ""] or rid == target_ticker:
                            addr = await self._resolve_address(vin)
                            name = await self.rune_resolver.resolve_name(rid)
                            seller_inputs.append((i, addr, amt, name))
                
                # Case B: Explicit Runestone transfers
                else:
                    for rune_id, amt in runes_transfers:
                        # Filter out the DEFAULT marker
                        if rune_id == "DEFAULT": continue
                        
                        if target_ticker in ["RUNES", ""] or rune_id == target_ticker:
                            addr = await self._resolve_address(vin)
                            name = await self.rune_resolver.resolve_name(rune_id)
                            seller_inputs.append((i, addr, amt, name))
                break # Process Runestones globally per TX
            
            # 2. BRC-20 trade discovery
            else:
                amt = await self.decoder.get_brc20_transfer_amount(vin["txid"], target_ticker)
                if amt and amt > 0:
                    addr = await self._resolve_address(vin)
                    seller_inputs.append((i, addr, amt, target_ticker))

        return await self._finalize_trades(tx, seller_inputs, asset_type)

    async def _discover_runes_from_inputs(self, tx: Dict) -> List[Tuple[str, int]]:
        """Identifies Runes in the inputs by inspecting parent transactions."""
        runes_found = []
        for vin in tx.get("vin", []):
            parent_txid = vin.get("txid")
            vout_idx = vin.get("vout")
            if parent_txid:
                parent_tx = self.decoder.cache.get(parent_txid)
                if not parent_tx: continue
                
                # Check for Runestone in parent targeting THIS vout_idx
                parent_results = await self.decoder.get_runes_transfer_amount(parent_tx)
                # TODO: Handle actual edict output matching. 
                # For now, if parent has Runestones, we assume they flowed to this input.
                if parent_results:
                    runes_found.extend(parent_results)
        return runes_found

    async def _resolve_address(self, vin: Dict) -> str:
        """Resolves the output address for a given input by looking up the parent transaction."""
        addr = vin.get("prevout", {}).get("scriptPubKey", {}).get("address")
        if not addr:
            parent_txid = vin.get("txid")
            if parent_txid:
                parent_tx = self.decoder.cache.get(parent_txid)
                if parent_tx:
                    vout_idx = vin.get("vout")
                    if vout_idx is not None and vout_idx < len(parent_tx.get("vout", [])):
                        addr = parent_tx["vout"][vout_idx].get("scriptPubKey", {}).get("address")
        return addr or "unknown"

    async def _finalize_trades(self, tx: Dict, seller_inputs: List[Tuple], asset_type: str) -> List[TradeFingerprint]:
        """Calculates total BTC payment to seller and identifies the counterparty."""
        trades = []
        txid = tx.get("txid", "")
        outputs = tx.get("vout", [])

        for vin_idx, seller_addr, asset_amount, ticker in seller_inputs:
            # SIGHASH_SINGLE Heuristic: The payment for input[i] is at output[i]
            sats_paid = 0
            if vin_idx < len(outputs):
                sats_paid = int(outputs[vin_idx].get("value", 0) * 10**8)
            
            # Fallback: sum all outputs back to seller address if SIGHASH_SINGLE index was empty
            if sats_paid == 0:
                for vout in outputs:
                    if vout.get("scriptPubKey", {}).get("address") == seller_addr:
                        sats_paid += int(vout.get("value", 0) * 10**8)

            if sats_paid > 0:
                buyer_addr = "unknown_buyer"
                for vin_b in tx.get("vin", []):
                    # Taker (Buyer) is the one without a SIGHASH_SINGLE signature
                    if not self._is_input_market_maker(vin_b):
                        addr = await self._resolve_address(vin_b)
                        if addr and addr != seller_addr:
                            buyer_addr = addr
                            break

                trades.append(TradeFingerprint(
                    txid=txid, asset_ticker=ticker, asset_amount=asset_amount,
                    sats_paid=sats_paid, seller_address=seller_addr, buyer_address=buyer_addr,
                    asset_type=asset_type
                ))
                logger.debug(f"Trade detected [{asset_type}:{ticker}]: {asset_amount} units for {sats_paid} sats.")
        return trades

    async def discover_trades_in_block(self, block: Dict) -> List[TradeFingerprint]:
        """Scans a full block to discover ALL asset trades dynamically."""
        all_trades = []
        # Filter transactions that look like they have marketplace signatures
        potential_txs = [tx for tx in block.get("tx", []) if isinstance(tx, dict) and self._is_market_maker_signature(tx)]
        if not potential_txs: return []

        # Prefetch parent transactions for all potential trades to resolve addresses
        parent_txids = [vin["txid"] for tx in potential_txs for vin in tx.get("vin", []) if "txid" in vin]
        if parent_txids:
            await self.decoder.prefetch_transactions(list(set(parent_txids)))

        for tx in potential_txs:
            # 1. Try to discover Runes trades dynamically
            runes_transfers = await self.decoder.get_runes_transfer_amount(tx)
            if runes_transfers:
                for rune_id, _ in runes_transfers:
                    trades = await self.extract_trades_from_tx(tx, rune_id, asset_type="RUNES")
                    all_trades.extend(trades)
                continue

            # 2. Try to discover BRC-20 trades dynamically
            for vin in tx.get("vin", []):
                if not self._is_input_market_maker(vin): continue
                
                parent_txid = vin.get("txid")
                if not parent_txid: continue
                
                # Check PRE-FETCHED parent for the BRC-20 transfer 'tick'
                # The inscription is in the parent (reveal) input witness
                parent_tx = self.decoder.cache.get(parent_txid)
                if not parent_tx: continue
                
                ticker = self._find_brc20_ticker_in_tx(parent_tx)
                if ticker:
                    trades = await self.extract_trades_from_tx(tx, ticker, asset_type="BRC20")
                    all_trades.extend(trades)
                    break
        return all_trades

    def _find_brc20_ticker_in_tx(self, tx: Dict) -> Optional[str]:
        """Scans a transaction's witnesses for BRC-20 transfer JSON."""
        for vin in tx.get("vin", []):
            for witness in vin.get("txinwitness", []):
                try:
                    decoded = binascii.unhexlify(witness).decode('utf-8', errors='ignore')
                    if '"p":"brc-20"' in decoded and '"op":"transfer"' in decoded:
                        import re
                        match = re.search(r'"tick":"([^"]+)"', decoded)
                        if match:
                            return match.group(1).upper().strip()
                except: continue
        return None
