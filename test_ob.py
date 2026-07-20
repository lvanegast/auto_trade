import asyncio
import aiohttp
import json

async def test():
    base_url = "https://api.limitless.exchange"
    async with aiohttp.ClientSession() as session:
        # Try different pages and trade types
        for tt in ["group", "clob", "amm", None]:
            for page in range(1, 6):
                url = f"{base_url}/markets/active?page={page}&limit=50"
                if tt:
                    url += f"&tradeType={tt}"
                try:
                    async with session.get(url, headers={"Accept": "application/json"}) as resp:
                        data = await resp.json()
                    markets = data.get("data", [])
                    total = data.get("totalMarketsCount", 0)
                    if not markets:
                        break
                    
                    types = {}
                    for m in markets:
                        tt2 = m.get("tradeType", "?")
                        mt = m.get("marketType", "?")
                        key = f"{tt2}/{mt}"
                        types[key] = types.get(key, 0) + 1
                    
                    print(f"Page {page} (filter={tt}): {len(markets)} items, total={total}, types={types}")
                    
                    # Check for multi-outcome
                    for m in markets:
                        mt = m.get("marketType", "")
                        if mt != "single":
                            print(f"  NON-SINGLE: {m.get('title')} | marketType={mt} | tradeType={m.get('tradeType')}")
                        
                        tags = m.get("tags", [])
                        if any("negrisk" in str(t).lower() or "group" in str(t).lower() or "multi" in str(t).lower() for t in tags):
                            print(f"  NEGRISK TAG: {m.get('title')} | tags={tags}")
                        
                        # Check for sub-markets in the data
                        if "markets" in m and isinstance(m["markets"], list) and len(m["markets"]) > 1:
                            print(f"  HAS SUB-MARKETS: {m.get('title')} | {len(m['markets'])} sub-markets")
                        
                        if "outcomeTokens" in m:
                            print(f"  OUTCOME TOKENS: {m.get('title')} | {m['outcomeTokens']}")
                except Exception as e:
                    print(f"Page {page} (filter={tt}): ERROR {e}")
                    break

        # Also search for sports markets (which are often NegRisk)
        print("\n=== Sports markets (automationType=sports) ===")
        for page in range(1, 3):
            url = f"{base_url}/markets/active?page={page}&limit=50&automationType=sports"
            try:
                async with session.get(url, headers={"Accept": "application/json"}) as resp:
                    data = await resp.json()
                markets = data.get("data", [])
                total = data.get("totalMarketsCount", 0)
                print(f"Sports page {page}: {len(markets)} items, total={total}")
                for m in markets[:5]:
                    print(f"  {m.get('title')} | type={m.get('tradeType')}/{m.get('marketType')} | tags={m.get('tags', [])}")
            except Exception as e:
                print(f"Sports page {page}: ERROR {e}")
                break

asyncio.run(test())
