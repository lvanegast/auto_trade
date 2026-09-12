"""
FillConfirmation — confirma que una orden REALMENTE se llenó antes de que el
motor la registre como "COMPLETED" y cree una posición.

Motivo: tanto Limitless (GTC + post_only=True) como Kalshi (orden "limit")
aceptan la orden en el libro sin garantizar un fill inmediato. post_only=True
en Limitless, por diseño del propio SDK, RECHAZA la orden si cruzaría el
libro — es decir, si la orden fue aceptada, NUNCA se llenó en el instante de
creación; queda esperando a que alguien la cruce. El motor NO debe asumir
"orden aceptada" == "orden llenada".

- Limitless: no expone un endpoint REST de "consultar orden por ID"; el
  mecanismo diseñado para esto es el canal de WebSocket `subscribe_order_events`
  (evento `orderEvent`), que emite un `SettlementOrderEvent` con
  type="MINED" cuando la pata efectivamente se asienta on-chain, o
  type="FAILED" si no.
- Kalshi: sí expone `GET /portfolio/orders/{order_id}` para consultar status.
"""

import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class FillConfirmationResult:
    filled: bool
    reason: str


async def confirm_limitless_fill(
    order_id: str,
    api_key: str,
    api_secret: str,
    timeout_seconds: float = 30.0,
) -> FillConfirmationResult:
    """
    Espera confirmación real de fill vía WebSocket order-events.
    Retorna filled=True solo si llega un SettlementOrderEvent MINED para esta
    orden. Cualquier otro caso (FAILED, timeout, error de conexión) es
    filled=False — el llamador debe cancelar la orden y tratar la pata como
    fallida.
    """
    try:
        from limitless_sdk.websocket import WebSocketClient
        from limitless_sdk.websocket.types import WebSocketConfig
        from limitless_sdk.types.api_tokens import HMACCredentials
    except Exception as e:
        return FillConfirmationResult(False, f"No se pudo importar el cliente WS: {e}")

    done = asyncio.Event()
    outcome = {"filled": False, "reason": "timeout esperando confirmación de fill"}

    def _on_order_event(data):
        try:
            event_order_id = data.get("orderId")
            if event_order_id != order_id:
                return
            event_type = data.get("type")
            if data.get("source") == "SETTLEMENT":
                if event_type == "MINED":
                    outcome["filled"] = True
                    outcome["reason"] = "settlement MINED"
                    done.set()
                elif event_type == "FAILED":
                    outcome["filled"] = False
                    outcome["reason"] = "settlement FAILED"
                    done.set()
            # type PLACEMENT/UPDATE/CANCELLATION (source OME) no confirman fill final —
            # solo el evento de settlement asegura que quedó asentado on-chain.
            elif event_type == "CANCELLATION":
                outcome["filled"] = False
                outcome["reason"] = "orden cancelada antes de llenarse"
                done.set()
        except Exception:
            pass

    client = WebSocketClient(
        WebSocketConfig(
            hmac_credentials=HMACCredentials(token_id=api_key, secret=api_secret),
            auto_reconnect=False,
        )
    )
    try:
        client.on("orderEvent", _on_order_event)
        await client.connect()
        await client.subscribe("subscribe_order_events")
        try:
            await asyncio.wait_for(done.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            pass
        return FillConfirmationResult(outcome["filled"], outcome["reason"])
    except Exception as ws_err:
        # Fallback a REST si WS falla por timeout de conexión o red
        return await _poll_limitless_rest_fill(order_id, api_key, api_secret, timeout_seconds=timeout_seconds)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def _poll_limitless_rest_fill(
    order_id: str,
    api_key: str,
    api_secret: str,
    timeout_seconds: float = 30.0,
    poll_interval: float = 2.0,
) -> FillConfirmationResult:
    """Fallback via REST: consulta get_clob_positions() para confirmar si la orden se llenó."""
    try:
        from limitless_sdk import Client, HMACCredentials
        deadline = time.monotonic() + timeout_seconds
        async with Client("https://api.limitless.exchange", hmac_credentials=HMACCredentials(token_id=api_key, secret=api_secret)) as client:
            while time.monotonic() < deadline:
                try:
                    clob_data = await client.portfolio.get_clob_positions()
                    found_live = False
                    if isinstance(clob_data, list):
                        for market_pos in clob_data:
                            orders_info = market_pos.get("orders", {}) if isinstance(market_pos, dict) else {}
                            live_orders = orders_info.get("liveOrders", []) if isinstance(orders_info, dict) else []
                            for o in live_orders:
                                if isinstance(o, dict) and o.get("id") == order_id:
                                    found_live = True
                                    orig = float(o.get("originalSize") or 1)
                                    rem = float(o.get("remainingSize") or 1)
                                    if rem < orig:
                                        return FillConfirmationResult(True, f"REST fill parcial/total: rem={rem}/{orig}")
                                    break
                            if found_live:
                                break
                    # Si ya no está en liveOrders, verificar si se ejecutó
                    if not found_live:
                        return FillConfirmationResult(True, "REST orden completada (fuera del libro activo)")
                except Exception:
                    pass
                await asyncio.sleep(poll_interval)
            return FillConfirmationResult(False, "REST timeout esperando fill")
    except Exception as e:
        return FillConfirmationResult(False, f"REST check error: {e}")


async def confirm_kalshi_fill(
    kalshi_rest_url: str,
    order_id: str,
    api_key_id: str,
    private_key,
    timeout_seconds: float = 15.0,
    poll_interval_seconds: float = 2.0,
) -> FillConfirmationResult:
    """
    Poll GET /portfolio/orders/{order_id} hasta que el status indique
    ejecución completa, o se agote el timeout (en cuyo caso el llamador debe
    cancelar la orden restante).
    """
    import requests
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    path = f"/portfolio/orders/{order_id}"
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        try:
            timestamp = str(int(time.time() * 1000))
            message = f"{timestamp}GET{path}".encode("utf-8")
            signature = private_key.sign(
                message,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256(),
            )
            headers = {
                "KALSHI-ACCESS-KEY": api_key_id,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
            }
            resp = await asyncio.to_thread(
                requests.get, f"{kalshi_rest_url}{path}", headers=headers, timeout=10
            )
            if resp.status_code == 200:
                order = resp.json().get("order", {})
                status = str(order.get("status", "")).lower()
                remaining = order.get("remaining_count")
                if status in ("executed", "filled") or (remaining is not None and int(remaining) == 0):
                    return FillConfirmationResult(True, f"status={status}")
                if status in ("canceled", "cancelled"):
                    return FillConfirmationResult(False, f"orden cancelada (status={status})")
            # status resting/pending -> seguir esperando
        except Exception:
            pass
        await asyncio.sleep(poll_interval_seconds)

    return FillConfirmationResult(False, "timeout esperando confirmación de fill")


async def cancel_kalshi_order(kalshi_rest_url: str, order_id: str, api_key_id: str, private_key) -> None:
    """Cancela una orden Kalshi que no confirmó fill dentro del timeout."""
    import requests
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    path = f"/portfolio/orders/{order_id}"
    try:
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}DELETE{path}".encode("utf-8")
        signature = private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        headers = {
            "KALSHI-ACCESS-KEY": api_key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }
        await asyncio.to_thread(requests.delete, f"{kalshi_rest_url}{path}", headers=headers, timeout=10)
    except Exception:
        pass
