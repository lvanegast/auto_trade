"""
RedeemExecutor — ejecuta redeem on-chain para cobrar shares ganadoras.

Dos modos:
- NegRisk markets: redeemPositions(conditionId, amounts) en NegRisk Adapter
- Standard CTF:    redeemPositions(conditionId, indexSets) en CTF

Ambos requieren eth_call simulación antes de enviar transacción real.
"""

import os
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class RedeemResult:
    """Resultado de un redeem."""
    success: bool
    market_slug: str
    condition_id: str
    winning_outcome: str
    shares_redeemed: float
    usdc_received: float
    tx_hash: Optional[str] = None
    error: Optional[str] = None


# ABI para NegRisk Adapter: redeemPositions(bytes32, uint256[])
# Source: Basescan tx 0x372c1ddb... MethodID: 0xdbeccb23
NEGRISK_REDEEM_ABI = [
    {
        "inputs": [
            {"name": "_conditionId", "type": "bytes32"},
            {"name": "_amounts", "type": "uint256[]"},
        ],
        "name": "redeemPositions",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

# ABI para Standard CTF: redeemPositions(bytes32, uint256[])
CTF_REDEEM_ABI = [
    {
        "inputs": [
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
        ],
        "name": "redeemPositions",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


class RedeemExecutor:
    """
    Ejecuta redeem on-chain para cobrar shares ganadoras.
    
    Para wallets EOA, el redeem se hace llamando
    a redeemPositions() en el contrato CTF o NegRisk Adapter on-chain.
    
    Uso:
        executor = RedeemExecutor(db, worker_id)
        result = await executor.redeem(condition_id, winning_outcome, shares)
    """
    
    # Contract addresses (Base Mainnet) — verified on Basescan
    CTF_ADDRESS = "0xC9c98965297Bc527861c898329Ee280632B76e18"
    NEGRISK_ADAPTER = "0x6151EF8368b6316c1aa3C68453EF083ad31E712D"  # v3
    
    def __init__(self, db, worker_id: str):
        self.db = db
        self.worker_id = worker_id
    
    async def redeem(
        self,
        condition_id: str,
        winning_outcome: str,
        shares: float,
        is_negrisk: bool = False,
    ) -> RedeemResult:
        """
        Ejecuta redeem on-chain para cobrar shares ganadoras.
        
        Args:
            condition_id: Condition ID del mercado (bytes32 hex)
            winning_outcome: "YES" o "NO"
            shares: Cantidad de shares a redeem
            is_negrisk: Si es un mercado NegRisk
            
        Returns:
            RedeemResult con detalles del redeem
        """
        if winning_outcome not in ("YES", "NO"):
            return RedeemResult(
                success=False,
                market_slug="",
                condition_id=condition_id,
                winning_outcome=winning_outcome,
                shares_redeemed=0,
                usdc_received=0,
                error=f"Invalid winning outcome: {winning_outcome}",
            )
        
        try:
            result = await self._redeem_onchain(condition_id, winning_outcome, shares, is_negrisk)
            return result
            
        except Exception as e:
            self.db.log(
                "ERROR",
                f"[RedeemExecutor] Error en redeem: {e}",
                self.worker_id,
            )
            return RedeemResult(
                success=False,
                market_slug="",
                condition_id=condition_id,
                winning_outcome=winning_outcome,
                shares_redeemed=0,
                usdc_received=0,
                error=str(e),
            )
    
    async def _redeem_onchain(
        self, condition_id: str, winning_outcome: str, shares: float, is_negrisk: bool
    ) -> RedeemResult:
        """
        Ejecuta redeem directamente on-chain via web3.
        
        Flujo:
        1. Simular con eth_call (detectar errores sin gastar gas)
        2. Si simulación exitosa → firmar y enviar transacción real
        3. Esperar confirmación
        """
        try:
            from web3 import Web3
            from eth_account import Account
        except ImportError:
            return RedeemResult(
                success=False,
                market_slug="",
                condition_id=condition_id,
                winning_outcome=winning_outcome,
                shares_redeemed=0,
                usdc_received=0,
                error="web3 not installed. Run: pip install web3",
            )
        
        # Obtener configuración
        private_key = os.getenv("LIMITLESS_PRIVATE_KEY")
        rpc_url = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
        
        if not private_key:
            return RedeemResult(
                success=False,
                market_slug="",
                condition_id=condition_id,
                winning_outcome=winning_outcome,
                shares_redeemed=0,
                usdc_received=0,
                error="LIMITLESS_PRIVATE_KEY not set",
            )
        
        try:
            # Conectar a Base
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            
            if not w3.is_connected():
                return RedeemResult(
                    success=False,
                    market_slug="",
                    condition_id=condition_id,
                    winning_outcome=winning_outcome,
                    shares_redeemed=0,
                    usdc_received=0,
                    error=f"Cannot connect to Base RPC: {rpc_url}",
                )
            
            # Configurar cuenta
            account = Account.from_key(private_key)
            wallet_address = account.address
            
            # Seleccionar contrato y parámetros según tipo
            if is_negrisk:
                # NegRisk Adapter: redeemPositions(bytes32 _conditionId, uint256[] _amounts)
                # Source: Basescan tx 0x372c1ddb — amounts = [winner_amount, loser_amount]
                contract_address = self.NEGRISK_ADAPTER
                abi = NEGRISK_REDEEM_ABI
                
                # USDC tiene 6 decimales
                amount_raw = int(shares * 1e6)
                
                if winning_outcome == "YES":
                    amounts = [amount_raw, 0]  # YES gana, NO pierde
                else:
                    amounts = [0, amount_raw]  # NO gana, YES pierde
                
                call_data = (condition_id, amounts)
            else:
                # Standard CTF: redeemPositions(bytes32 conditionId, uint256[] indexSets)
                # indexSets: YES = 1 (binary 01), NO = 2 (binary 10)
                # Source: Basescan PayoutRedemption events — indexSets = [1, 2]
                contract_address = self.CTF_ADDRESS
                abi = CTF_REDEEM_ABI
                
                index_sets = [1] if winning_outcome == "YES" else [2]
                call_data = (condition_id, index_sets)
            
            # Crear instancia del contrato
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(contract_address),
                abi=abi,
            )
            
            # PASO 1: Simular con eth_call (detectar errores sin gastar gas)
            try:
                simulation_result = contract.functions.redeemPositions(*call_data).call(
                    {"from": wallet_address}
                )
                self.db.log(
                    "INFO",
                    f"[RedeemExecutor] eth_call simulación exitosa: {simulation_result}",
                    self.worker_id,
                )
            except Exception as sim_error:
                # Simulación falló — no enviar transacción real
                return RedeemResult(
                    success=False,
                    market_slug="",
                    condition_id=condition_id,
                    winning_outcome=winning_outcome,
                    shares_redeemed=0,
                    usdc_received=0,
                    error=f"eth_call simulation failed: {sim_error}",
                )
            
            # PASO 2: Estimar gas
            try:
                gas_estimate = contract.functions.redeemPositions(*call_data).estimate_gas(
                    {"from": wallet_address}
                )
                gas_limit = int(gas_estimate * 1.2)  # 20% buffer
            except Exception as e:
                gas_limit = 200000
                self.db.log(
                    "WARNING",
                    f"[RedeemExecutor] Gas estimation failed, using default 200k: {e}",
                    self.worker_id,
                )
            
            # PASO 3: Construir, firmar y enviar transacción
            gas_price = w3.eth.gas_price
            nonce = w3.eth.get_transaction_count(wallet_address)
            
            tx = contract.functions.redeemPositions(*call_data).build_transaction({
                "from": wallet_address,
                "gas": gas_limit,
                "gasPrice": gas_price,
                "nonce": nonce,
                "chainId": 8453,  # Base mainnet
            })
            
            signed_tx = w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = tx_hash.hex()
            
            self.db.log(
                "INFO",
                f"[RedeemExecutor] Transacción enviada: {tx_hash_hex}",
                self.worker_id,
            )
            
            # PASO 4: Esperar confirmación (máximo 60 segundos)
            try:
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                
                if receipt["status"] == 1:
                    self.db.log(
                        "INFO",
                        f"[RedeemExecutor] Redeem exitoso: tx={tx_hash_hex}, gas_used={receipt['gasUsed']}",
                        self.worker_id,
                    )
                    return RedeemResult(
                        success=True,
                        market_slug="",
                        condition_id=condition_id,
                        winning_outcome=winning_outcome,
                        shares_redeemed=shares,
                        usdc_received=shares * 1.0,  # Aproximado
                        tx_hash=tx_hash_hex,
                    )
                else:
                    return RedeemResult(
                        success=False,
                        market_slug="",
                        condition_id=condition_id,
                        winning_outcome=winning_outcome,
                        shares_redeemed=0,
                        usdc_received=0,
                        tx_hash=tx_hash_hex,
                        error=f"Transaction failed: status={receipt['status']}",
                    )
                    
            except Exception as e:
                return RedeemResult(
                    success=False,
                    market_slug="",
                    condition_id=condition_id,
                    winning_outcome=winning_outcome,
                    shares_redeemed=0,
                    usdc_received=0,
                    tx_hash=tx_hash_hex,
                    error=f"Transaction timeout or error: {e}",
                )
                
        except Exception as e:
            return RedeemResult(
                success=False,
                market_slug="",
                condition_id=condition_id,
                winning_outcome=winning_outcome,
                shares_redeemed=0,
                usdc_received=0,
                error=f"On-chain redeem error: {e}",
            )


# Singleton
_redeem_executor: Optional[RedeemExecutor] = None


def get_redeem_executor(db=None, worker_id: str = None) -> RedeemExecutor:
    """Obtiene o crea la instancia global de RedeemExecutor."""
    global _redeem_executor
    if _redeem_executor is None and db is not None:
        _redeem_executor = RedeemExecutor(db, worker_id)
    return _redeem_executor
