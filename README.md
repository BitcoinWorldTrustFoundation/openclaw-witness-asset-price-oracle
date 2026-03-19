# 🐾 Witness Oracle Ecosystem | The Truth Miner

**A 100% On-Chain, Stateless Price & Asset Oracle for Bitcoin.**

Derived directly from L1 Witness data, this ecosystem provides trustless pricing for BTC (Thermodynamic Consensus) and L1 Assets (BRC-20, Runes) using heuristic marketplace fingerprinting. Zero external APIs. Zero local databases. Pure on-chain truth.

---

## 🛠 Features

### 1. Witness BTC Price Oracle
- **Thermodynamic Extraction**: Uses UTXOracle v9.1 logic to derive fiat value from UTXO distributions.
- **Entropy Guard**: Enforces a minimum of 10,000 transactions across the scanning window to resist price manipulation.
- **Binohash Seal**: Applies a Proof-of-Work seal to every state JSON for cryptographic integrity.
- **Strict Output**: Returns `price_cents_uint64`, optimized for Bitcoin covenants and Simplicity scripts.

### 2. Witness Asset Oracle (Heartbeat)
- **Heuristic Discovery**: Fingerprints marketplace trades (UniSat, Magic Eden, OKX) directly from SegWit v0 and Taproot witnesses.
- **VWAP Median Pricing**: Calculates the volume-weighted median price for assets like BRC-20s and Runes.
- **Volatility Circuit Breaker**: Stabilizes the feed with a Time-Decay mechanism to prevent oracle freezes during flash crashes.
- **Global Block Scan**: Heartbeat report sent for every block, ranking the Top 5 assets by on-chain volume.

---

## 🚀 Installation

```bash
git clone https://github.com/BitcoinWorldTrustFoundation/openclaw-witness-asset-price-oracle.git
cd openclaw-witness-asset-price-oracle
./install.sh
```

## 🔌 Quick Start

### 1. Configuration
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
# Edit .env with your TELEGRAM_BOT_TOKEN and RPC providers
```

### 2. Launch
Run the unified ecosystem launcher:
```bash
./go-announcer.sh
```

---

## 📊 Sample Output

### BTC Pricing (JSON Sealed)
```json
{
  "height": 941330,
  "price_cents_uint64": 6942515,
  "delta_pct": -0.022,
  "data_age_blocks": 36,
  "timestamp": 1773949718,
  "source": "UTXOracle_v9.1_Native",
  "nonce": 139,
  "binohash": "0021d60eae75c45f2978ec4340a0a14623c40a5dfdd28d019bfc50194e111270"
}
```

### Asset Witness Report
```text
🧊 Witness L1 Block Scan: 941307
💰 BTC Price: $69,701.95

🔥 Top 5 BRC-20 (by volume):
1. ORDI: $42.50 (Vol: 1.2 BTC)
...

💎 Top 5 Runes (by volume):
1. DOG•GO•TO•THE•MOON: $0.0051 (Vol: 0.8 BTC)
...

⚡ Trustless extraction. Zero API. Pure L1 Witness Math.
```

---

## 🛡 Security & Audit
- **Zero API Reliance**: No dependencies on CoinGecko, UniSat API, or Mempool.space API.
- **Multi-RPC Failover**: Rotates between providers to ensure high availability and resistance to rate limiting.
- **Stateless Design**: Each consensus run is deterministic and can be audited from any Bitcoin node.

**Built for the Bitcon World Trust Foundation.**  
**The Truth Miner is here.** 🐾🚀🏁
