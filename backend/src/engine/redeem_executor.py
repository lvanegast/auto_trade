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

# ABI para Standard CTF: redeemPositions(address, bytes32, bytes32, uint256[])
CTF_REDEEM_ABI = [
    {
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
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
                # Standard CTF: redeemPositions(address collateralToken, bytes32 parentCollectionId, bytes32 conditionId, uint256[] indexSets)
                # indexSets: [1, 2] redeems both YES/NO outcomes (winning pays out, losing pays 0)
                contract_address = self.CTF_ADDRESS
                abi = CTF_REDEEM_ABI
                collateral_token = os.getenv("USDC_ADDRESS", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
                parent_collection_id = b"\x00" * 32
                cond_bytes = bytes.fromhex(condition_id[2:] if condition_id.startswith("0x") else condition_id)
                index_sets = [1, 2]
                call_data = (
                    Web3.to_checksum_address(collateral_token),
                    parent_collection_id,
                    cond_bytes,
                    index_sets,
                )
            
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

    async def auto_redeem_clob_portfolio(self) -> List[RedeemResult]:
        """
        Escanea directamente la cartera CLOB en Limitless (ground-truth).
        Para cualquier mercado resuelto donde tengamos tokens ganadores > 0:
        ejecuta el redeem on-chain y alerta por Telegram.
        """
        results: List[RedeemResult] = []
        api_key = os.getenv("LIMITLESS_API_KEY")
        api_secret = os.getenv("LIMITLESS_API_SECRET")
        private_key = os.getenv("LIMITLESS_PRIVATE_KEY")

        if not api_key or not api_secret or not private_key:
            return results

        try:
            from limitless_sdk import Client as LimitlessClient, HMACCredentials
            async with LimitlessClient(
                "https://api.limitless.exchange",
                hmac_credentials=HMACCredentials(token_id=api_key, secret=api_secret),
            ) as client:
                clob_data = await client.portfolio.get_clob_positions()
                if not isinstance(clob_data, list):
                    return results

                for item in clob_data:
                    if not isinstance(item, dict):
                        continue
                    market = item.get("market") or {}
                    status = market.get("status")
                    if status != "RESOLVED":
                        continue

                    market_slug = market.get("slug", "")
                    condition_id = market.get("conditionId") or market.get("condition_id")
                    if not condition_id:
                        continue

                    tokens_bal = item.get("tokensBalance") or {}
                    raw_yes = float(tokens_bal.get("yes", 0) or 0)
                    raw_no = float(tokens_bal.get("no", 0) or 0)

                    yes_shares = raw_yes / 1e6 if raw_yes >= 1000 else raw_yes
                    no_shares = raw_no / 1e6 if raw_no >= 1000 else raw_no

                    if yes_shares <= 0.001 and no_shares <= 0.001:
                        continue

                    # Determinar ganador
                    winning_idx = market.get("winningOutcomeIndex")
                    if winning_idx is None:
                        winning_idx = market.get("winning_outcome_index")

                    is_negrisk = market.get("marketType") == "group" or market.get("market_type") == "group"
                    winning_outcome = None
                    if winning_idx is not None:
                        winning_outcome = "YES" if winning_idx == 0 else "NO"
                    else:
                        try:
                            from limitless_sdk.markets import MarketFetcher
                            fetcher = MarketFetcher(client.http)
                            m_detail = await fetcher.get_market(market_slug)
                            w_idx = getattr(m_detail, "winning_outcome_index", None)
                            if w_idx is not None:
                                winning_outcome = "YES" if w_idx == 0 else "NO"
                        except Exception:
                            pass

                    if not winning_outcome:
                        continue

                    winning_shares = yes_shares if winning_outcome == "YES" else no_shares
                    if winning_shares <= 0.001:
                        continue

                    self.db.log(
                        "INFO",
                        f"[AutoRedeem] 🎯 Detectado contrato ganador en {market_slug}: {winning_shares:.2f} {winning_outcome}. Ejecutando redeem on-chain...",
                        self.worker_id,
                    )

                    res = await self.redeem(
                        condition_id=condition_id,
                        winning_outcome=winning_outcome,
                        shares=winning_shares,
                        is_negrisk=is_negrisk,
                    )
                    res.market_slug = market_slug
                    results.append(res)

                    if res.success:
                        self.db.log(
                            "INFO",
                            f"[AutoRedeem] ✅ Redeem exitoso para {market_slug}: tx={res.tx_hash}, {winning_shares:.2f} USDC recibidos",
                            self.worker_id,
                        )
                        # Notificar Telegram
                        try:
                            from src.telegram_bot import telegram_bot
                            if telegram_bot.enabled:
                                cat = "crypto" if ("up-or-down" in market_slug or "crypto" in market_slug.lower()) else "sports"
                                telegram_bot.send_payout_received(
                                    worker_id=self.worker_id,
                                    market_slug=market_slug,
                                    token=winning_outcome,
                                    amount_won=winning_shares,
                                    payout_usd=winning_shares * 1.0,
                                    cost_usd=winning_shares * 0.50,
                                    net_profit_usd=winning_shares * 0.50,
                                    tx_hash=res.tx_hash,
                                    category=cat,
                                )
                        except Exception as e_tg:
                            print(f"[AutoRedeem TG Error] {e_tg}")

                        # Actualizar en BD local si existía alguna posición
                        try:
                            if hasattr(self.db, "get_open_positions") and hasattr(self.db, "mark_position_redeemed"):
                                positions = self.db.get_open_positions(worker_id=self.worker_id) or []
                                for p in positions:
                                    if market_slug in p.get("symbol", ""):
                                        self.db.mark_position_redeemed(p["id"])
                                        self.db.close_position(
                                            p["id"], 1.0, exit_reason="AutoRedeem OnChain", worker_id=self.worker_id
                                        )
                        except Exception:
                            pass
                    else:
                        self.db.log(
                            "CRITICAL",
                            f"[AutoRedeem] ❌ Falló redeem on-chain para {market_slug}: {res.error}",
                            self.worker_id,
                        )
        except Exception as e:
            self.db.log("WARNING", f"[AutoRedeem] Error escaneando clob_positions: {e}", self.worker_id)

        return results


# Singleton
_redeem_executor: Optional[RedeemExecutor] = None


def get_redeem_executor(db=None, worker_id: str = None) -> RedeemExecutor:
    """Obtiene o crea la instancia global de RedeemExecutor."""
    global _redeem_executor
    if _redeem_executor is None and db is not None:
        _redeem_executor = RedeemExecutor(db, worker_id)
    return _redeem_executor
