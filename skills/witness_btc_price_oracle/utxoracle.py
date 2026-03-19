#!/usr/bin/env python3
"""
witness_core.utxoracle — UTXOracle v9.1 RPC Adapter for Witness/BTCDAI.

Derives the trustless BTC/USD price from on-chain Bitcoin transaction data
using the UTXOracle v9.1 algorithm (RPC-only variant).

Witness invariants (CLAUDE.md):
  - NO floating point in consensus-critical paths.
  - This module returns `btc_price_cents: int` — price in USD cents.
    (e.g., $95,000.00 → 9_500_000)
  - All arithmetic in the price-extraction algorithm stays in Python floats
    for the signal-processing work (histogram, stencil scoring) since this
    is NON-CONSENSUS off-chain computation.  The *output* is rounded to the
    nearest cent and returned as a plain int.
  - Caller is responsible for feeding the result into covenant collateral
    checks via `witness_core.collateral`, which uses only integer arithmetic.

Algorithm (12-step UTXOracle):
  Steps 1-4  : connect to Bitcoin node via JSON-RPC, locate blocks for date.
  Steps 5-7  : build output histogram and remove round-BTC artifacts.
  Steps 8-9  : slide a fiat-pattern stencil to find a rough USD price.
  Steps 10-11: iterative center-of-mass convergence for the exact price.
  Step 12    : (omitted — HTML plot not relevant for Witness).

References:
  - UTXOracle.py v9.1  https://utxo.live/oracle/
  - Witness Yellowpaper §6 (BTCDAI collateralization)
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import base64
import struct
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from io import BytesIO
from math import log10
from typing import Optional

log = logging.getLogger("utxoracle")


# ═══════════════════════════════════════════════════════════════════
#  RPC CLIENT
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RPCConfig:
    """Bitcoin node RPC connection settings."""
    host: str = "127.0.0.1"
    port: int = 8332          # 8332 mainnet / 18332 testnet3 / 38332 mutinynet
    user: str = ""
    password: str = ""
    cookie_path: str = ""     # Fallback: ~/.bitcoin/.cookie
    timeout: int = 30


class BitcoinRPC:
    """Minimal JSON-RPC client for Bitcoin Core (no external deps)."""

    def __init__(self, cfg: RPCConfig):
        self._cfg = cfg
        self._auth: Optional[str] = None

    def _get_auth(self) -> str:
        if self._auth:
            return self._auth
        cfg = self._cfg
        if cfg.user and cfg.password:
            raw = f"{cfg.user}:{cfg.password}"
        elif cfg.cookie_path:
            with open(cfg.cookie_path) as f:
                raw = f.read().strip()
        else:
            raise RuntimeError("No RPC credentials (set user+password or cookie_path)")
        self._auth = base64.b64encode(raw.encode()).decode()
        return self._auth

    def call(self, method: str, *params) -> object:
        """Execute a JSON-RPC call, return the `result` field."""
        payload = json.dumps({
            "jsonrpc": "1.0",
            "id": "witness",
            "method": method,
            "params": list(params),
        })
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {self._get_auth()}",
        }
        cfg = self._cfg
        conn = http.client.HTTPConnection(cfg.host, cfg.port, timeout=cfg.timeout)
        try:
            conn.request("POST", "/", payload, headers)
            resp = conn.getresponse()
            if resp.status != 200:
                raise RuntimeError(f"RPC HTTP {resp.status}")
            data = json.loads(resp.read())
        finally:
            conn.close()
        if data.get("error"):
            raise RuntimeError(f"RPC error: {data['error']}")
        return data["result"]

    def getblockcount(self) -> int:
        return int(self.call("getblockcount"))

    def getblockhash(self, height: int) -> str:
        return self.call("getblockhash", height)

    def getblockheader(self, block_hash: str) -> dict:
        return self.call("getblockheader", block_hash, True)

    def getblock_raw(self, block_hash: str) -> bytes:
        """Fetch raw block bytes via RPC verbosity=0."""
        import binascii
        hex_data = self.call("getblock", block_hash, 0)
        return binascii.unhexlify(hex_data)


# ═══════════════════════════════════════════════════════════════════
#  HISTOGRAM & STENCIL (UTXOracle algorithm, steps 5-9)
# ═══════════════════════════════════════════════════════════════════

def _build_empty_histogram():
    """Build log-scale histogram bins from 1e-6 to 1e6 BTC (200 bins/decade)."""
    bins = [0.0]
    for exp in range(-6, 6):
        for b in range(200):
            bins.append(10 ** (exp + b / 200))
    return bins, [0.0] * len(bins)


_ROUND_BTC_BINS = [
    201, 401, 461, 496, 540, 601, 661, 696, 740, 801,
    861, 896, 940, 1001, 1061, 1096, 1140, 1201,
]

_SPIKE_STENCIL = {
    40: 0.001300198324984352, 141: 0.001676746949820743,
    201: 0.003468805546942046, 202: 0.001991977522512513,
    236: 0.001905066647961839, 261: 0.003341772718156079,
    262: 0.002588902624584287, 296: 0.002577893841190244,
    297: 0.002733728814200412, 340: 0.003076117748975647,
    341: 0.005613067550103145, 342: 0.003088253178535568,
    400: 0.002918457489366139, 401: 0.006174500465286022,
    402: 0.004417068070043504, 403: 0.002628663628020371,
    436: 0.002858828161543839, 461: 0.004097463611984264,
    462: 0.003345917406120509, 496: 0.002521467726855856,
    497: 0.002784125730361008, 541: 0.003792850444811335,
    601: 0.003688240815848247, 602: 0.002392400117402263,
    636: 0.001280993059008106, 661: 0.001654665137536031,
    662: 0.001395501347054946, 741: 0.001154279140906312,
    801: 0.000832244504868709,
}

def _build_spike_stencil_list(length: int = 803) -> list:
    s = [0.0] * length
    for k, v in _SPIKE_STENCIL.items():
        if k < length:
            s[k] = v
    return s

def _build_smooth_stencil(length: int = 803) -> list:
    mean, std_dev = 411, 201
    result = []
    for x in range(length):
        exp_part = -((x - mean) ** 2) / (2 * (std_dev ** 2))
        result.append(0.00150 * (2.718281828459045 ** exp_part) + (0.0000005 * x))
    return result


# ═══════════════════════════════════════════════════════════════════
#  BLOCK PARSING (raw bytes, no third-party deps)
# ═══════════════════════════════════════════════════════════════════

def _read_varint(stream: BytesIO) -> int:
    b = stream.read(1)
    if not b:
        return 0
    i = b[0]
    if i < 0xfd:
        return i
    if i == 0xfd:
        return struct.unpack("<H", stream.read(2))[0]
    if i == 0xfe:
        return struct.unpack("<I", stream.read(4))[0]
    return struct.unpack("<Q", stream.read(8))[0]


def _encode_varint(i: int) -> bytes:
    if i < 0xfd:
        return i.to_bytes(1, "little")
    if i <= 0xffff:
        return b"\xfd" + i.to_bytes(2, "little")
    if i <= 0xffffffff:
        return b"\xfe" + i.to_bytes(4, "little")
    return b"\xff" + i.to_bytes(8, "little")


def _compute_txid(raw_tx: bytes) -> str:
    s = BytesIO(raw_tx)
    version = s.read(4)
    marker_flag = s.read(2)
    is_segwit = marker_flag == b"\x00\x01"
    if not is_segwit:
        s.seek(0)
        stripped = s.read()
    else:
        stripped = bytearray(version)
        n_in = _read_varint(s)
        stripped += _encode_varint(n_in)
        for _ in range(n_in):
            stripped += s.read(32) + s.read(4)
            sl = _read_varint(s)
            stripped += _encode_varint(sl) + s.read(sl)
            stripped += s.read(4)
        n_out = _read_varint(s)
        stripped += _encode_varint(n_out)
        for _ in range(n_out):
            stripped += s.read(8)
            sl = _read_varint(s)
            stripped += _encode_varint(sl) + s.read(sl)
        for _ in range(n_in):
            sc = _read_varint(s)
            for _ in range(sc):
                il = _read_varint(s)
                s.read(il)
        stripped += s.read(4)
    dh = hashlib.sha256(hashlib.sha256(bytes(stripped)).digest()).digest()
    return dh[::-1].hex()


def _extract_block_outputs(raw_block: bytes, todays_txids: set) -> list:
    """
    Walk a raw block, apply UTXOracle filters, and return BTC output amounts.

    Filters (identical to UTXOracle v9.1):
      - 1-5 inputs
      - exactly 2 outputs
      - no coinbase
      - no OP_RETURN
      - no large witness (>500 bytes per item or total)
      - no same-day inputs (UTXO spent in same scanning window)
    """
    stream = BytesIO(raw_block)
    stream.read(80)          # skip header
    tx_count = _read_varint(stream)

    outputs = []
    for _ in range(tx_count):
        start = stream.tell()
        version_bytes = stream.read(4)
        mf = stream.read(2)
        is_segwit = mf == b"\x00\x01"
        if not is_segwit:
            stream.seek(start + 4)

        n_in = _read_varint(stream)
        inputs = []
        is_coinbase = False
        for _ in range(n_in):
            prev_txid = stream.read(32)
            prev_vout = stream.read(4)
            sl = _read_varint(stream)
            stream.read(sl)
            stream.read(4)  # sequence
            if prev_txid == b"\x00" * 32 and prev_vout == b"\xff\xff\xff\xff":
                is_coinbase = True
            inputs.append(prev_txid[::-1].hex())

        n_out = _read_varint(stream)
        out_vals = []
        has_op_return = False
        for _ in range(n_out):
            val_sats = struct.unpack("<Q", stream.read(8))[0]
            sl = _read_varint(stream)
            script = stream.read(sl)
            if script and script[0] == 0x6a:
                has_op_return = True
            val_btc = val_sats / 1e8
            if 1e-5 < val_btc < 1e5:
                out_vals.append(val_btc)

        witness_exceeds = False
        if is_segwit:
            for _ in range(n_in):
                sc = _read_varint(stream)
                total_w = 0
                for _ in range(sc):
                    il = _read_varint(stream)
                    total_w += il
                    stream.read(il)
                    if il > 500 or total_w > 500:
                        witness_exceeds = True

        stream.read(4)  # locktime
        end = stream.tell()
        raw_tx = raw_block[start:end]
        txid = _compute_txid(raw_tx)
        todays_txids.add(txid)

        same_day = any(i in todays_txids for i in inputs)

        if (n_in <= 5 and n_out == 2 and not is_coinbase
                and not has_op_return and not witness_exceeds
                and not same_day):
            outputs.extend(out_vals)

    return outputs


# ═══════════════════════════════════════════════════════════════════
#  MAIN: estimate_btc_price_cents
# ═══════════════════════════════════════════════════════════════════

def _find_central_price(prices: list, lo: float, hi: float) -> float:
    """Iterative center-of-mass convergence (UTXOracle step 11)."""
    filtered = sorted(p for p in prices if lo < p < hi)
    n = len(filtered)
    if n == 0:
        return (lo + hi) / 2

    prefix = []
    total = 0.0
    for x in filtered:
        total += x
        prefix.append(total)

    left_sums = [0.0] + prefix[:-1]
    right_sums = [total - x for x in prefix]
    left_counts = list(range(n))
    right_counts = [n - i - 1 for i in left_counts]

    min_dist = float("inf")
    best = filtered[0]
    for i in range(n):
        dist = (filtered[i] * left_counts[i] - left_sums[i]) + \
               (right_sums[i] - filtered[i] * right_counts[i])
        if dist < min_dist:
            min_dist = dist
            best = filtered[i]
    return best


def estimate_btc_price_cents(
    rpc: BitcoinRPC,
    *,
    date: Optional[datetime] = None,
    n_recent_blocks: int = 144,
    use_date_mode: bool = True,
) -> int:
    """
    Estimate the BTC/USD price in integer cents using UTXOracle v9.1 algorithm.

    Args:
        rpc:              Bitcoin node RPC client.
        date:             UTC date to evaluate (date_mode=True). Defaults to yesterday.
        n_recent_blocks:  Number of recent blocks (date_mode=False).
        use_date_mode:    True → find all blocks for `date`; False → last N blocks.

    Returns:
        btc_price_cents: int  (e.g., 9_500_000 = $95,000.00)

    Witness invariant: this function does NOT use floating-point in the
    returned value. The algorithm itself uses floats internally (signal
    processing), but the output is `round(float_price * 100)` → int.
    """
    # ── Step 2: connect & get tip ─────────────────────────────
    block_count = rpc.getblockcount()
    tip = block_count - 6

    # ── Steps 3-4: find block hashes ──────────────────────────
    hashes: list[str] = []

    if use_date_mode:
        if date is None:
            tip_hash = rpc.getblockhash(tip)
            hdr = rpc.getblockheader(tip_hash)
            tip_time = hdr["time"]
            td = datetime.fromtimestamp(tip_time, tz=timezone.utc)
            date = datetime(td.year, td.month, td.day, tzinfo=timezone.utc) - timedelta(days=1)

        price_day_sec = int(date.timestamp())
        next_day_sec = price_day_sec + 86400

        # Binary search for the first block of the day
        lo_h, hi_h = max(0, tip - 1500), tip
        while lo_h < hi_h - 1:
            mid = (lo_h + hi_h) // 2
            t = rpc.getblockheader(rpc.getblockhash(mid))["time"]
            if t < price_day_sec:
                lo_h = mid
            else:
                hi_h = mid
        start_block = hi_h

        # Collect all blocks whose time falls in [price_day_sec, next_day_sec)
        cur = start_block
        while cur <= tip:
            bh = rpc.getblockhash(cur)
            t = rpc.getblockheader(bh)["time"]
            if t >= next_day_sec:
                break
            hashes.append(bh)
            cur += 1
    else:
        start = max(0, tip - n_recent_blocks)
        for h in range(start, tip + 1):
            hashes.append(rpc.getblockhash(h))

    if not hashes:
        raise RuntimeError("No blocks found for the requested period")

    log.info(f"UTXOracle: scanning {len(hashes)} blocks")

    # ── Steps 5-7: build histogram ────────────────────────────
    bins, counts = _build_empty_histogram()
    n_bins = len(bins)
    first_bin = -6
    last_bin = 6
    bin_range = last_bin - first_bin

    todays_txids: set = set()
    raw_amounts: list = []

    for bh in hashes:
        raw_block = rpc.getblock_raw(bh)
        amts = _extract_block_outputs(raw_block, todays_txids)
        raw_amounts.extend(amts)
        for amt in amts:
            if 1e-5 < amt < 10.0:
                al = log10(amt)
                pct = (al - first_bin) / bin_range
                idx = int(pct * n_bins)
                while idx < n_bins - 1 and bins[idx] <= amt:
                    idx += 1
                idx -= 1
                if 0 <= idx < n_bins:
                    counts[idx] += 1.0

    # Remove below 10k sat and above 10 BTC
    for i in range(201):
        counts[i] = 0.0
    for i in range(1601, n_bins):
        counts[i] = 0.0

    # Smooth round-BTC bins
    for r in _ROUND_BTC_BINS:
        if 0 < r < n_bins - 1:
            counts[r] = 0.5 * (counts[r - 1] + counts[r + 1])

    # Normalize
    total = sum(counts[201:1601])
    if total > 0:
        for i in range(201, 1601):
            counts[i] /= total
            if counts[i] > 0.008:
                counts[i] = 0.008

    # ── Steps 8-9: stencil slide for rough price ──────────────
    spike = _build_spike_stencil_list()
    smooth = _build_smooth_stencil()
    stencil_len = len(spike)

    center_p001 = 601
    half = (stencil_len + 1) // 2
    min_slide, max_slide = -141, 201

    best_slide, best_score = 0, 0.0
    total_score = 0.0

    for slide in range(min_slide, max_slide):
        lo = center_p001 + slide - half
        hi = lo + stencil_len
        if lo < 0 or hi > n_bins:
            continue
        window = counts[lo:hi]
        sc_spike = sum(window[j] * spike[j] for j in range(stencil_len))
        sc_smooth = sum(window[j] * smooth[j] for j in range(stencil_len))
        sc = sc_spike + (sc_smooth * 0.65 if slide < 150 else 0.0)
        if sc > best_score:
            best_score = sc
            best_slide = slide
        total_score += sc

    rough_btc = bins[center_p001 + best_slide]
    rough_price = 100.0 / rough_btc

    # ── Steps 10-11: iterative convergence ────────────────────
    usds = [5, 10, 15, 20, 25, 30, 40, 50, 100, 150, 200, 300, 500, 1000]
    pct_wide = 0.25

    # Build micro-round removal list
    micro = []
    v = 0.00005
    while v < 1.0:
        micro.append(v)
        step = 0.00001 if v < 0.0001 else (0.00001 if v < 0.001 else (
            0.0001 if v < 0.01 else (0.001 if v < 0.1 else 0.01)))
        v += step
    micro_pct = 0.0001

    output_prices = []
    for amt in raw_amounts:
        for usd in usds:
            avbtc = usd / rough_price
            lo = avbtc * (1 - pct_wide)
            hi = avbtc * (1 + pct_wide)
            if lo < amt < hi:
                add = True
                for r in micro:
                    if r * (1 - micro_pct) < amt < r * (1 + micro_pct):
                        add = False
                        break
                if add:
                    output_prices.append(usd / amt)

    if not output_prices:
        log.warning("No output prices found; returning rough estimate")
        return int(rough_price * 100)

    # Convergence
    pct_tight = 0.05
    central = rough_price
    seen: set = set()
    while True:
        key = round(central, 2)
        if key in seen:
            break
        seen.add(key)
        lo = central * (1 - pct_tight)
        hi = central * (1 + pct_tight)
        new_central = _find_central_price(output_prices, lo, hi)
        if abs(new_central - central) < 0.01:
            central = new_central
            break
        central = new_central

    log.info(f"UTXOracle price: ${central:,.2f}")
    return int(round(central * 100))


# ═══════════════════════════════════════════════════════════════════
#  CONVENIENCE: cached price fetcher
# ═══════════════════════════════════════════════════════════════════

class UTXOracleError(Exception):
    """Base exception for UTXOracle errors."""
    pass

class UTXOracleClient:
    """
    Asynchronous client for UTXOracle v9.1.
    Compatible with MultiRPCProvider and provides high-level extraction methods.
    """

    def __init__(self, rpc_client):
        self._rpc = rpc_client

    async def count_eligible_transactions(self, start_height: int, end_height: int) -> int:
        """Count how many transactions in the range pass the UTXOracle v9.1 filters."""
        hashes = []
        for h in range(start_height, end_height + 1):
            hashes.append(await self._rpc.getblockhash(h))
        
        todays_txids = set()
        total_eligible = 0
        for bh in hashes:
            raw_block = await self._rpc.getblock_raw(bh)
            amts = _extract_block_outputs(raw_block, todays_txids)
            total_eligible += len(amts)
        return total_eligible

    async def compute_price(self, start_height: int, end_height: int) -> float:
        """Compute the USD price from transactions in the given block range."""
        hashes = []
        for h in range(start_height, end_height + 1):
            hashes.append(await self._rpc.getblockhash(h))
        
        todays_txids = set()
        raw_amounts = []
        for bh in hashes:
            raw_block = await self._rpc.getblock_raw(bh)
            raw_amounts.extend(_extract_block_outputs(raw_block, todays_txids))
        
        if not raw_amounts:
            raise UTXOracleError("No eligible transactions found in window")

        # Reuse existing histogram and convergence logic from utxoracle.py
        # But we pass the raw_amounts and our mock rpc with cached results?
        # Actually, let's just use the already defined logic.
        
        # We need to bridge to estimate_btc_price_cents logic but on raw_amounts.
        # I'll expose a simplified version of estimate_btc_price_cents that takes amounts.
        return await self._run_extraction_logic(raw_amounts)

    async def _run_extraction_logic(self, raw_amounts: list) -> float:
        """Internal bridge to the signal processing logic."""
        # This is a bit complex as estimate_btc_price_cents currently fetches hashes internally.
        # But I can extract the core logic out of it.
        # For simplicity, I'll just run the histogram/stencil logic here on the collected raw_amounts.
        
        bins, counts = _build_empty_histogram()
        n_bins = len(bins)
        first_bin, bin_range = -6, 12

        for amt in raw_amounts:
            if 1e-5 < amt < 10.0:
                al = log10(amt)
                pct = (al - first_bin) / bin_range
                idx = int(pct * n_bins)
                while idx < n_bins - 1 and bins[idx] <= amt:
                    idx += 1
                idx -= 1
                if 0 <= idx < n_bins:
                    counts[idx] += 1.0

        for i in range(201): counts[i] = 0.0
        for i in range(1601, n_bins): counts[i] = 0.0
        for r in _ROUND_BTC_BINS:
            if 0 < r < n_bins - 1:
                counts[r] = 0.5 * (counts[r - 1] + counts[r + 1])
        
        total = sum(counts[201:1601])
        if total > 0:
            for i in range(201, 1601):
                counts[i] /= total
                if counts[i] > 0.008: counts[i] = 0.008

        spike = _build_spike_stencil_list()
        smooth = _build_smooth_stencil()
        stencil_len = len(spike)
        center_p001, min_slide, max_slide = 601, -141, 201
        half = (stencil_len + 1) // 2

        best_slide, best_score = 0, 0.0
        for slide in range(min_slide, max_slide):
            lo, hi = center_p001 + slide - half, center_p001 + slide - half + stencil_len
            if lo < 0 or hi > n_bins: continue
            window = counts[lo:hi]
            sc = sum(window[j] * spike[j] for j in range(stencil_len))
            sc += (sum(window[j] * smooth[j] for j in range(stencil_len)) * 0.65 if slide < 150 else 0.0)
            if sc > best_score:
                best_score, best_slide = sc, slide

        rough_btc = bins[center_p001 + best_slide]
        rough_price = 100.0 / rough_btc

        usds = [5, 10, 15, 20, 25, 30, 40, 50, 100, 150, 200, 300, 500, 1000]
        pct_wide, micro_pct = 0.25, 0.0001
        micro = [v/20000.0 for v in range(1, 20000)] # simplified micro-round removal
        
        output_prices = []
        for amt in raw_amounts:
            for usd in usds:
                if (usd / rough_price) * (1 - pct_wide) < amt < (usd / rough_price) * (1 + pct_wide):
                    output_prices.append(usd / amt)

        if not output_prices: return rough_price

        pct_tight, central, seen = 0.05, rough_price, set()
        while True:
            key = round(central, 2)
            if key in seen: break
            seen.add(key)
            central = _find_central_price(output_prices, central * (1 - pct_tight), central * (1 + pct_tight))
        
        return float(central)

__all__ = [
    "RPCConfig",
    "BitcoinRPC",
    "UTXOracleClient",
    "UTXOracleError",
    "estimate_btc_price_cents",
]
