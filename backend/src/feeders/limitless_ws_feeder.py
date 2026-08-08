"""
LimitlessWebSocketFeeder — feeder en tiempo real usando WebSocket de Limitless.

Reemplaza el polling HTTP por actualizaciones push del orderbook.
Elimina la necesidad de delays y evita rate limiting de Cloudflare.

Usa el SDK oficial: limitless_sdk.websocket.client.WebSocketClient
"""

import asyncio
import os
import time
from typing import Optional, Dict, List
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent
from src.utils.bounded_dict import BoundedDict


class LimitlessWebSocketFeeder(BaseFeeder):
    """
    Feeder que usa WebSocket para recibir actualizaciones de precios en tiempo real.
    
    Ventajas sobre polling:
    - Sin llamadas HTTP repetitivas → no hay rate limiting
    - Actualizaciones instantáneas (<100ms)
    - Menor latencia detectada
    - Sin necesidad de delays artificiales
    """
    
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol.upper(), event_queue)
        self.ws_client = None
        self._ws_task = None
        self._market_slugs: List[str] = []
        self._last_prices: Dict[str, dict] = BoundedDict(max_size=200)
        
    async def start(self):
        """Inicia el feeder WebSocket."""
        self.running = True
        print(f"[Feeder Limitless WS] Iniciando WebSocket para {self.symbol}...")
        self._ws_task = asyncio.create_task(self._run_websocket())
        
    async def stop(self):
        """Detiene el feeder WebSocket."""
        self.running = False
        if self.ws_client:
            await self.ws_client.disconnect()
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
    
    async def _run_websocket(self):
        """Ejecuta la conexión WebSocket."""
        from limitless_sdk.websocket.client import WebSocketClient
        from limitless_sdk.websocket.types import WebSocketConfig
        from limitless_sdk.types.api_tokens import HMACCredentials
        
        api_key = os.getenv("LIMITLESS_API_KEY")
        api_secret = os.getenv("LIMITLESS_API_SECRET")
        
        config = WebSocketConfig(
            auto_reconnect=True,
            reconnect_delay=2.0,
            timeout=10.0,
        )
        
        # Configurar autenticación si hay credenciales
        if api_key and api_secret:
            config.hmac_credentials = HMACCredentials(token_id=api_key, secret=api_secret)
        
        self.ws_client = WebSocketClient(config=config)
        
        # Registrar handler para actualizaciones de precios
        @self.ws_client.on('priceUpdate')
        async def on_price_update(data):
            await self._handle_price_update(data)
        
        @self.ws_client.on('orderbookUpdate')
        async def on_orderbook_update(data):
            await self._handle_orderbook_update(data)
        
        try:
            await self.ws_client.connect()
            print(f"[Feeder Limitless WS] Conectado a WebSocket")
            
            # Suscribirse a mercados activos
            await self._subscribe_to_markets()
            
            # Mantener conexión viva y re-suscribir a nuevos mercados activos cada 60s
            last_sub_time = time.time()
            while self.running:
                await asyncio.sleep(5)
                if time.time() - last_sub_time > 60:
                    last_sub_time = time.time()
                    try:
                        await self._subscribe_to_markets()
                    except Exception as e_resub:
                        print(f"[Feeder Limitless WS] Error re-suscribiendo mercados: {e_resub}")
                
        except asyncio.CancelledError:
            print(f"[Feeder Limitless WS] Tarea cancelada")
        except Exception as e:
            print(f"[Feeder Limitless WS] Error: {e}")
        finally:
            if self.ws_client:
                await self.ws_client.disconnect()
    
    async def _subscribe_to_markets(self):
        """Suscribe a mercados activos vía WebSocket."""
        try:
            # Obtener slugs de mercados activos
            from limitless_sdk.api import HttpClient
            from limitless_sdk.markets import MarketFetcher
            
            async with HttpClient() as http:
                fetcher = MarketFetcher(http)
                
                # Suscribirse a mercados crypto
                if "CRYPTO" in self.symbol or "ANY" in self.symbol:
                    await self._subscribe_crypto_markets(fetcher)
                
                # Suscribirse a mercados deportivos
                elif "SPORTS" in self.symbol:
                    await self._subscribe_sports_markets(fetcher)
                    
        except Exception as e:
            print(f"[Feeder Limitless WS] Error suscribiendo mercados: {e}")
    
    async def _subscribe_crypto_markets(self, fetcher):
        """Suscribe a mercados de crypto activos."""
        try:
            from limitless_sdk.market_pages import MarketPageFetcher
            from limitless_sdk.api import HttpClient
            
            async with HttpClient() as http:
                page_fetcher = MarketPageFetcher(http)
                crypto_page_id = "5e76699e-8763-4c91-85de-3efeb064efec"
                resp = await page_fetcher.get_markets(crypto_page_id, {"limit": 20})
                markets = resp.data if hasattr(resp, "data") else []
                
                slugs = []
                for m in markets[:15]:
                    slug = m.slug if hasattr(m, "slug") else ""
                    if slug:
                        slugs.append(slug)
                
                if slugs:
                    await self.ws_client.subscribe(
                        'subscribe_market_prices',
                        {'marketSlugs': slugs}
                    )
                    print(f"[Feeder Limitless WS] Suscrito a {len(slugs)} mercados crypto")
                    
        except Exception as e:
            print(f"[Feeder Limitless WS] Error suscribiendo crypto: {e}")
    
    async def _subscribe_sports_markets(self, fetcher):
        """Suscribe a mercados deportivos activos."""
        try:
            await self.ws_client.subscribe(
                'subscribe_live_sports',
                {}
            )
            print(f"[Feeder Limitless WS] Suscrito a live sports")
        except Exception as e:
            print(f"[Feeder Limitless WS] Error suscribiendo sports: {e}")
    
    async def _handle_price_update(self, data):
        """Maneja actualizaciones de precios del WebSocket."""
        try:
            start_time = time.time()
            
            # Extraer datos del update
            slug = data.get("slug", "")
            price = float(data.get("price", 0.0))
            bid_raw = data.get("bid")
            ask_raw = data.get("ask")
            
            if not slug or price <= 0:
                return

            if bid_raw is None or ask_raw is None:
                # Mensaje de precio sin libro ejecutable — no fabricar bid/ask
                return
            bid = float(bid_raw)
            ask = float(ask_raw)
            if bid <= 0 or ask <= 0 or ask <= bid:
                return
            
            # Registrar latencia del WebSocket (instantánea)
            from src.engine.latency_tracker import latency_tracker
            latency_ms = (time.time() - start_time) * 1000
            latency_tracker._record(type('Measurement', (), {
                'platform': 'limitless',
                'operation': 'ws_price_update',
                'latency_ms': latency_ms,
                'success': True,
                'start_time': start_time,
                'end_time': time.time(),
            })())
            
            # Crear evento
            event = PriceUpdateEvent(
                symbol=f"limitless_crypto_{slug}",
                price=price,
                bid=bid,
                ask=ask,
            )
            
            # Actualizar cache
            self._last_prices[slug] = {
                "price": price,
                "bid": bid,
                "ask": ask,
                "timestamp": time.time(),
            }
            
            # Enviar a la cola
            await self.queue.put(event)
            
        except Exception as e:
            print(f"[Feeder Limitless WS] Error procesando price update: {e}")
    
    async def _handle_orderbook_update(self, data):
        """Maneja actualizaciones del orderbook del WebSocket."""
        try:
            start_time = time.time()
            
            slug = data.get("slug", "")
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            
            if not slug:
                return
            
            # Mejor bid/ask
            best_bid = float(bids[0]["price"]) if bids else 0.0
            best_ask = float(asks[0]["price"]) if asks else 0.0
            
            if best_bid <= 0 or best_ask <= 0:
                return
            
            mid_price = (best_bid + best_ask) / 2.0
            
            # Registrar latencia
            from src.engine.latency_tracker import latency_tracker
            latency_ms = (time.time() - start_time) * 1000
            latency_tracker._record(type('Measurement', (), {
                'platform': 'limitless',
                'operation': 'ws_orderbook_update',
                'latency_ms': latency_ms,
                'success': True,
                'start_time': start_time,
                'end_time': time.time(),
            })())
            
            # Actualizar tracker cross-platform
            from src.strategy.cross_platform_tracker import cross_platform_tracker
            cross_platform_tracker.update_book(
                event_id=f"limitless_{slug}",
                platform="limitless",
                yes_bid=best_bid,
                yes_ask=best_ask,
                no_bid=round(1.0 - best_ask, 4),
                no_ask=round(1.0 - best_bid, 4),
            )
            
            # Crear evento
            event = PriceUpdateEvent(
                symbol=f"limitless_crypto_{slug}",
                price=mid_price,
                bid=best_bid,
                ask=best_ask,
            )
            
            await self.queue.put(event)
            
        except Exception as e:
            print(f"[Feeder Limitless WS] Error procesando orderbook update: {e}")
