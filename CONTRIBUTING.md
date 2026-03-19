# Contributing to Witness Native UTXOracle

Thank you for being part of the Bitcoin sovereign future!

## Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/BitcoinWorldTrustFoundation/openclaw-witness-asset-price-oracle.git
   cd openclaw-witness-asset-price-oracle
   ```

2. **Run the Setup Wizard**:
   ```bash
   ./install.sh
   ```

3. **Install dev dependencies**:
   ```bash
   pip install -e ".[dev]"
   ```

## Development Rules

- **Pure PHP-native extraction**: Keep the `utxoracle.py` logic deterministic. No floats in final outputs.
- **RPC Solidarity**: Ensure all new features are compatible with common Bitcoin JSON-RPC implementations.
- **Testing**: Every PR must include tests in the `tests/` folder. Run `pytest` before submitting.

## How to Submit Changes

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/amazing-logic`).
3. Commit your changes (`git commit -m 'Add amazing logic'`).
4. Push to the branch (`git push origin feature/amazing-logic`).
5. Open a Pull Request.

---

**Sovereignty begins with code auditability.** 🛡️
