"""
Limitless API Helper — Llamadas HTTP robustas a Limitless Exchange.

Protege al bot contra errores de validación de schema de Pydantic (ValidationError)
cuando Limitless añade, elimina o modifica campos en su API pública.
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("LimitlessApiHelper")

KNOWN_PAGE_IDS = {
    "/sport": "2a91349c-3308-4234-afb7-0663e42968c1",
    "/esports": "f2a04a4e-580a-4cd1-bcc9-c23ed9ff8916",
    "/crypto": "5e76699e-8763-4c91-85de-3efeb064efec",
    "/finance": "4962ba38-2482-4e33-beff-2d3eb49f15bb",
}


async def fetch_markets_safe(http_client, page_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Obtiene los mercados de una página de Limitless en formato JSON crudo (dict).
    Evita los crashes por ValidationError del SDK oficial cuando cambia el schema.
    """
    if not http_client or not page_id:
        return []
    try:
        endpoint = f"/market-pages/{page_id}/markets?limit={limit}"
        response_data = await http_client.get(endpoint)
        if isinstance(response_data, dict):
            return response_data.get("data", []) or []
        elif isinstance(response_data, list):
            return response_data
        return []
    except Exception as e:
        logger.warning(f"Error fetching raw markets for page {page_id}: {e}")
        return []


async def get_page_id_safe(http_client, path: str) -> Optional[str]:
    """
    Obtiene el ID de página para un path (/sport, /esports, etc.)
    con fallback a los UUIDs canónicos conocidos si la API falla.
    """
    # 1. Fallback inmediato conocido
    normalized_path = "/" + path.strip("/")
    known_id = KNOWN_PAGE_IDS.get(normalized_path)
    
    if not http_client:
        return known_id

    try:
        resp = await http_client.get("/market-pages")
        if isinstance(resp, list):
            for p in resp:
                if isinstance(p, dict) and p.get("path") == normalized_path:
                    return p.get("id")
    except Exception:
        pass

    return known_id
