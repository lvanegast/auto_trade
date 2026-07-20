import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8')
from limitless_sdk.api import HttpClient
from limitless_sdk.markets import MarketFetcher

async def go():
    hc = HttpClient()
    mf = MarketFetcher(hc)
    resp = await mf.get_active_markets()
    markets = resp.data if hasattr(resp, 'data') else []
    crypto = [m for m in markets if 'up' in m.slug.lower() or 'down' in m.slug.lower()]
    print("Total active: %d, crypto up/down: %d" % (len(markets), len(crypto)))
    for m in crypto[:3]:
        print("  %s | %s | prices=%s" % (m.slug, m.title, m.prices))
    await hc.close()

asyncio.run(go())
