import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from skills.witness_btc_price_oracle.utxoracle_engine import (
    UTXOracleEngine,
    InsufficientEntropyError
)
# Note: UTXOracleNodeError was removed as it's not defined in the current engine
from skills.witness_btc_price_oracle.utxoracle import UTXOracleClient, UTXOracleError

@pytest.fixture
def mock_rpc_provider():
    provider = MagicMock()
    provider.getblockcount = AsyncMock(return_value=850000)
    provider.close = AsyncMock()
    return provider

@pytest.fixture
def engine(mock_rpc_provider):
    # On instancie le moteur avec des paramètres réduits pour les tests
    eng = UTXOracleEngine(
        rpc_urls=["http://fake-node.local"],
        window_size=2,
        min_entropy=100,
        max_expansion=10
    )
    # On injecte notre provider mocké
    eng.provider = mock_rpc_provider
    eng.core_utxo_client = AsyncMock(spec=UTXOracleClient)
    return eng

@pytest.mark.asyncio
async def test_get_price_success_first_try(engine):
    """
    Test le cas idéal : l'entropie est suffisante dès la première fenêtre (window_size=2).
    """
    # L'entropie retournée (150) est supérieure au minimum (100)
    engine.core_utxo_client.count_eligible_transactions.return_value = 150
    # Le prix retourné par l'algorithme 12-step est 65432.10 USD
    engine.core_utxo_client.compute_price.return_value = 65432.10

    price_cents, scanned_blocks = await engine.get_price_for_consensus(current_height=850000)

    # Vérifications
    assert price_cents == 6543210  # Conversion stricte en uint64 cents
    assert scanned_blocks == 2
    engine.core_utxo_client.count_eligible_transactions.assert_called_once_with(849999, 850000)
    engine.core_utxo_client.compute_price.assert_called_once_with(849999, 850000)

@pytest.mark.asyncio
async def test_get_price_with_window_expansion(engine):
    """
    Test l'expansion dynamique : l'entropie est faible au début, le moteur recule dans le temps.
    """
    # 1er appel (2 blocs) : 50 txs -> Échec (min 100)
    # 2ème appel (2+6 = 8 blocs) : 120 txs -> Succès
    engine.core_utxo_client.count_eligible_transactions.side_effect = [50, 120]
    engine.core_utxo_client.compute_price.return_value = 65000.00

    price_cents, scanned_blocks = await engine.get_price_for_consensus(current_height=850000)

    assert price_cents == 6500000
    assert scanned_blocks == 8
    assert engine.core_utxo_client.count_eligible_transactions.call_count == 2
    # Le deuxième appel doit scanner de (850000 - 8 + 1) à 850000
    engine.core_utxo_client.count_eligible_transactions.assert_called_with(849993, 850000)

@pytest.mark.asyncio
async def test_get_price_insufficient_entropy_abort(engine):
    """
    Test la sécurité anti-manipulation : le moteur atteint max_expansion sans trouver d'entropie.
    """
    # Retourne toujours une entropie trop faible (10 txs)
    engine.core_utxo_client.count_eligible_transactions.return_value = 10

    with pytest.raises(InsufficientEntropyError) as exc_info:
        await engine.get_price_for_consensus(current_height=850000)

    assert "Failed to reach entropy threshold" in str(exc_info.value)
    # La fenêtre s'est étendue de 2, puis 8, mais max_expansion est 10. La boucle s'arrête.

@pytest.mark.asyncio
async def test_rpc_failure_aborts_consensus(engine):
    """
    Test la sécurité L1 : si le nœud RPC meurt pendant le calcul du prix, on crashe proprement.
    """
    # Simule une erreur de connexion réseau lors du calcul du prix
    engine.core_utxo_client.count_eligible_transactions.return_value = 500
    engine.core_utxo_client.compute_price.side_effect = UTXOracleError("RPC Timeout")

    with pytest.raises(UTXOracleError) as exc_info:
        await engine.get_price_for_consensus(current_height=850000)

    assert "RPC Timeout" in str(exc_info.value)
