from skills.witness_btc_price_oracle.binohash import compute_binohash, verify_binohash

def test_binohash_determinism():
    """Verify that the same data always produces the same hash."""
    data = {
        "height": 850000,
        "price_cents_uint64": 6500000,
        "source": "UTXOracle_v9.1_Native"
    }
    hash1 = compute_binohash(data)
    hash2 = compute_binohash(data)
    assert hash1 == hash2

def test_binohash_integrity_failure():
    """Verify that any modification to the data results in a hash mismatch."""
    data = {
        "height": 850000,
        "price_cents_uint64": 6500000
    }
    original_hash = compute_binohash(data)
    
    # Modify data
    tampered_data = data.copy()
    tampered_data["price_cents_uint64"] = 6500001
    
    assert verify_binohash(tampered_data, original_hash) is False

def test_binohash_key_ordering():
    """Verify that key ordering in the dict doesn't change the hash (Canonicalization)."""
    data1 = {"a": 1, "b": 2}
    data2 = {"b": 2, "a": 1}
    assert compute_binohash(data1) == compute_binohash(data2)

def test_binohash_verification_success():
    """Verify that the utility can verify its own exported hash."""
    data = {"height": 100, "price": 500}
    bhash = compute_binohash(data)
    
    data_with_hash = data.copy()
    data_with_hash["binohash"] = bhash
    
    assert verify_binohash(data_with_hash, bhash) is True
