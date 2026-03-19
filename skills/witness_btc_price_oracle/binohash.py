import json
import hashlib
import logging
from typing import Any, Dict

logger = logging.getLogger("witness.binohash")

DIFFICULTY = 2  # Default number of leading hex zeros (W)

def compute_binohash(data: Dict[str, Any], difficulty: int = DIFFICULTY) -> str:
    """
    Computes a Binohash (Proof-of-Work) for a dictionary.
    The hash must start with 'difficulty' number of leading hex zeros ('0').
    
    This hash serves as an integrity guard for the Witness L1 truth.
    """
    clean_data = {k: v for k, v in data.items() if k != 'binohash'}
    target = '0' * difficulty
    
    nonce = 0
    while True:
        clean_data["nonce"] = nonce
        # Canonical JSON serialization
        canonical_json = json.dumps(clean_data, sort_keys=True, separators=(',', ':')).encode('utf-8')
        h = hashlib.sha256(canonical_json).hexdigest()
        
        # Verify work (W-target check)
        if h.startswith(target):
            # We must return the hash, ensuring the data includes the valid nonce
            data["nonce"] = nonce
            return h
        
        nonce += 1
        if nonce % 100000 == 0:
            logger.debug(f"Grinding binohash... nonce={nonce}")

def verify_binohash(data: Dict[str, Any], expected_hash: str) -> bool:
    """Verifies that the data matches the provided Binohash Proof."""
    # We use compute_binohash to see if it produces the same hash for the current nonce
    clean_data = {k: v for k, v in data.items() if k != 'binohash'}
    canonical_json = json.dumps(clean_data, sort_keys=True, separators=(',', ':')).encode('utf-8')
    h = hashlib.sha256(canonical_json).hexdigest()
    return h == expected_hash
