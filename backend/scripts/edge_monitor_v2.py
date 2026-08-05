"""
Cross-Platform Edge Monitor v2 — Resilient with DB persistence.

Observes esports markets between Limitless and Kalshi.
Saves snapshots to PostgreSQL so data survives restarts.
"""

import asyncio
import json
import os
import sys
import time
import base64
import urllib.request
from datetime import datetime

sys.path.insert(0, '/app')

SNAPSHOT_INTERVAL = 180  # 3 minutes
DURATION_HOURS = 6
LIMITLESS_TAKER_FEE = 0.0236
KALSHI_TAKER_FEE = 0.007


def get_db():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'db_trading'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'trading_bot'),
        user=os.getenv('DB_USER', 'trading_user'),
        password=os.getenv('DB_PASSWORD', 'trading_password'),
    )


def save_snapshot(db, snapshot):
    cur = db.cursor()
    if not snapshot.get('opportunities'):
        cur.execute("""
            INSERT INTO edge_snapshots
            (platform_a, platform_b, event_id, event_title, edge_pct,
             liquidity_verified, viable)
            VALUES ('limitless', 'kalshi', '', '__NO_OPPORTUNITY__', 0, FALSE, FALSE)
        """)
    for opp in snapshot.get('opportunities', []):
        cur.execute("""
            INSERT INTO edge_snapshots
            (platform_a, platform_b, event_id, event_title, edge_pct, gross_edge_pct,
             platform_a_yes_ask, platform_b_no_ask, platform_a_depth, platform_b_depth,
             liquidity_verified, viable)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            opp.get('platform_a', 'limitless'),
            opp.get('platform_b', 'kalshi'),
            opp.get('event_id', ''),
            opp.get('event_title', ''),
            opp.get('net_edge_pct', 0),
            opp.get('gross_edge_pct', 0),
            opp.get('platform_a_yes_ask', 0),
            opp.get('platform_b_no_ask', 0),
            opp.get('platform_a_depth', 0),
            opp.get('platform_b_depth', 0),
            opp.get('liquidity_verified', False),
            opp.get('viable', False),
        ))
    db.commit()
    cur.close()


def get_kalshi_markets():
    key_path = os.getenv('KALSHI_PRIVATE_KEY_PATH', '/app/arb.pem')
    api_key_id = os.getenv('KALSHI_API_KEY_ID')

    if not api_key_id or not os.path.exists(key_path):
        return []

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    with open(key_path, 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    def kr(method, path):
        ts = str(int(time.time() * 1000))
        msg = f'{ts}{method}{path}'.encode()
        sig = private_key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
        req = urllib.request.Request('https://external-api.kalshi.com' + path, method=method, headers={
            'User-Agent': 'M',
            'KALSHI-ACCESS-KEY': api_key_id,
            'KALSHI-ACCESS-SIGNATURE': base64.b64encode(sig).decode(),
            'KALSHI-ACCESS-TIMESTAMP': ts,
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())

    markets = []
    for series in ['KXLOLGAME', 'KXATPMATCH']:
        try:
            events = kr('GET', '/trade-api/v2/events?limit=20&status=open&series_ticker=' + series)
            for e in events.get('events', []):
                event_title = e.get('title', '')
                ticker = e.get('event_ticker', '')
                ms = kr('GET', '/trade-api/v2/markets?limit=5&status=open&event_ticker=' + ticker)
                for m in ms.get('markets', []):
                    vol = float(m.get('volume_fp', 0) or 0)
                    if vol < 100:
                        continue
                    yes_bid = float(m.get('yes_bid_dollars', 0) or 0)
                    yes_ask = float(m.get('yes_ask_dollars', 0) or 0)
                    yes_ask_size = float(m.get('yes_ask_size_fp', 0) or 0)
                    if yes_ask > 0:
                        markets.append({
                            'ticker': m.get('ticker', ''),
                            'title': m.get('title', ''),
                            'event_title': event_title,
                            'yes_bid': yes_bid,
                            'yes_ask': yes_ask,
                            'yes_ask_size': yes_ask_size,
                            'volume': vol,
                        })
        except Exception as e:
            print(f'[Kalshi] Error fetching {series}: {e}')

    return markets


def get_limitless_markets():
    try:
        from limitless_sdk.api import HttpClient
        from limitless_sdk.market_pages import MarketPageFetcher

        async def fetch():
            http = HttpClient()
            page_fetcher = MarketPageFetcher(http)
            result = []
            for page_id in ['2a91349c-3308-4234-afb7-0663e42968c1', 'f2a04a4e-580a-4cd1-bcc9-c23ed9ff8916']:
                try:
                    resp = await page_fetcher.get_markets(page_id, {'limit': 100})
                    markets = resp.data if hasattr(resp, 'data') else (resp.get('data', []) if isinstance(resp, dict) else [])
                    for m in markets:
                        title = m.title if hasattr(m, 'title') else m.get('title', '')
                        slug = m.slug if hasattr(m, 'slug') else m.get('slug', '')
                        subs = getattr(m, 'markets', None) or (m.get('markets') if isinstance(m, dict) else None)
                        if subs:
                            for sub in subs:
                                sub_title = getattr(sub, 'title', '') or (sub.get('title', '') if isinstance(sub, dict) else '')
                                sub_slug = getattr(sub, 'slug', '') or (sub.get('slug', '') if isinstance(sub, dict) else '')
                                sub_prices = getattr(sub, 'prices', None) or (sub.get('prices', []) if isinstance(sub, dict) else [])
                                if sub_prices and len(sub_prices) >= 1:
                                    result.append({
                                        'title': sub_title,
                                        'slug': sub_slug,
                                        'parent_title': title,
                                        'yes_price': sub_prices[0],
                                    })
                except Exception as e:
                    print(f'[Limitless] Error: {e}')
            await http.close()
            return result

        return asyncio.run(fetch())
    except Exception as e:
        print(f'[Limitless] Fatal error: {e}')
        return []


def normalize(title):
    import re
    normalized = title.lower().strip().replace('.', '').replace(',', '').replace('vs.', 'vs')
    normalized = re.sub(r'\s+', ' ', normalized)
    parts = normalized.split(' vs ')
    if len(parts) == 2:
        team_a = parts[0].strip()
        team_b = parts[1].strip()
        if team_a > team_b:
            team_a, team_b = team_b, team_a
        return f'{team_a.replace(" ", "-")}-vs-{team_b.replace(" ", "-")}'
    return normalized.replace(' ', '-')


def get_limitless_executable_price(slug):
    """Get real executable bid/ask from Limitless orderbook with caching."""
    from src.limitless_price_cache import async_get_limitless_executable_price
    return asyncio.run(async_get_limitless_executable_price(slug))


def normalize_team(title):
    """Normalize a team name for matching."""
    import re
    normalized = title.lower().strip().replace('.', '').replace(',', '')
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized


def match_teams(ll_title, k_title):
    """Check if two team names refer to the same team."""
    ll = normalize_team(ll_title)
    k = normalize_team(k_title)

    # Direct match
    if ll == k:
        return True

    # Common abbreviations
    abbrevs = {
        't1': ['t1'],
        'hanwha': ['hanwha life esports', 'hanwha'],
        'gen.g': ['geng', 'gen.g'],
    }

    for key, variants in abbrevs.items():
        ll_match = any(v in ll for v in variants)
        k_match = any(v in k for v in variants)
        if ll_match and k_match:
            return True

    # NO partial match — too error-prone
    # e.g., "mcon" should NOT match "bandits"
    return False


def take_snapshot():
    timestamp = datetime.utcnow().isoformat()
    print(f'\n[{timestamp}] Taking snapshot...')

    kalshi = get_kalshi_markets()
    limitless = get_limitless_markets()
    print(f'  Kalshi: {len(kalshi)} markets, Limitless: {len(limitless)} markets')

    # Build normalized lookup for Kalshi by event
    k_by_norm = {}
    for km in kalshi:
        title = km.get('event_title', '')
        n = normalize(title)
        if n not in k_by_norm:
            k_by_norm[n] = []
        k_by_norm[n].append(km)

    # Build normalized lookup for Limitless by event
    ll_by_norm = {}
    for lm in limitless:
        n = normalize(lm.get('parent_title', ''))
        if n not in ll_by_norm:
            ll_by_norm[n] = []
        ll_by_norm[n].append(lm)

    # Find overlaps
    overlaps = []
    for norm_key in set(ll_by_norm.keys()) & set(k_by_norm.keys()):
        ll_markets = ll_by_norm[norm_key]
        k_markets = k_by_norm[norm_key]
        overlaps.append({
            'norm_key': norm_key,
            'limitless': ll_markets,
            'kalshi': k_markets,
        })

    print(f'  Overlaps: {len(overlaps)}')

    snapshot = {
        'timestamp': timestamp,
        'kalshi_count': len(kalshi),
        'limitless_count': len(limitless),
        'overlap_count': len(overlaps),
        'opportunities': [],
    }

    for overlap in overlaps:
        # For each overlap (event), find the best arb opportunity across all sub-markets
        best_opp = None
        best_edge = -999

        for ll in overlap['limitless']:
            ll_team = ll.get('title', '')

            # Find the matching Kalshi market for this team
            matching_km = None
            for km in overlap['kalshi']:
                km_title = km.get('title', '')
                km_team = km_title.replace('Will ', '').split(' win the ')[0] if 'win the' in km_title else km_title

                if match_teams(ll_team, km_team):
                    matching_km = km
                    break

            if not matching_km:
                continue

            # Get REAL executable price from Limitless orderbook
            ll_ob = get_limitless_executable_price(ll.get('slug', ''))
            if not ll_ob:
                continue

            ll_ask = ll_ob.get('yes_ask', 0)
            ll_depth = ll_ob.get('ask_size', 0)

            # For the SAME team: buy YES on Limitless, buy NO on Kalshi
            km_no_ask = 1.0 - matching_km.get('yes_bid', 0)

            if ll_ask <= 0 or km_no_ask <= 0:
                continue

            cost = ll_ask + km_no_ask
            edge = 1.0 - cost
            net_edge = edge - ll_ask * LIMITLESS_TAKER_FEE - km_no_ask * KALSHI_TAKER_FEE

            # Track the best opportunity for this event
            if net_edge > best_edge:
                best_edge = net_edge
                best_opp = {
                    'platform_a': 'limitless',
                    'platform_b': 'kalshi',
                    'event_id': overlap['norm_key'],
                    'event_title': f"{ll.get('parent_title', '')} [{ll_team}]",
                    'edge_pct': round(edge * 100, 2),
                    'gross_edge_pct': round(edge * 100, 2),
                    'platform_a_yes_ask': ll_ask,
                    'platform_b_no_ask': km_no_ask,
                    'platform_a_depth': ll_depth,
                    'platform_b_depth': matching_km.get('yes_ask_size', 0),
                    'liquidity_verified': ll_depth > 0 and matching_km.get('yes_ask_size', 0) > 0,
                    'net_edge_pct': round(net_edge * 100, 2),
                    'viable': net_edge >= 0.0225 and ll_depth > 0 and matching_km.get('yes_ask_size', 0) > 0,
                }

        # Only add the best opportunity for this event (no duplicates)
        if best_opp:
            snapshot['opportunities'].append(best_opp)
            status = '✅ VIABLE' if best_opp['viable'] else '❌'
            print(f'  {status} {overlap["norm_key"]}: gross={best_opp["gross_edge_pct"]}% net={best_opp["net_edge_pct"]}% '
                  f'LL_ask={best_opp["platform_a_yes_ask"]} K_no_ask={best_opp["platform_b_no_ask"]} '
                  f'depth_LL={best_opp["platform_a_depth"]} K={best_opp["platform_b_depth"]}')

    return snapshot


def main():
    db = get_db()
    start_time = time.time()
    end_time = start_time + (DURATION_HOURS * 3600)
    snapshot_count = 0

    print(f'=== Cross-Platform Edge Monitor v2 ===')
    print(f'Interval: {SNAPSHOT_INTERVAL}s ({SNAPSHOT_INTERVAL // 60} min)')
    print(f'Duration: {DURATION_HOURS}h')
    print(f'DB: PostgreSQL (edge_snapshots table)')
    print()

    while time.time() < end_time:
        try:
            snapshot = take_snapshot()
            save_snapshot(db, snapshot)
            snapshot_count += 1

            viable_count = sum(1 for o in snapshot['opportunities'] if o['viable'])
            max_edge = max((o['edge_pct'] for o in snapshot['opportunities']), default=0)
            print(f'  Summary: {viable_count} viable, max_edge={max_edge}% (saved to DB)')

        except Exception as e:
            print(f'  Error: {e}')

        time.sleep(SNAPSHOT_INTERVAL)

    db.close()
    print(f'\n=== Monitor complete ===')
    print(f'Snapshots taken: {snapshot_count}')


if __name__ == '__main__':
    main()
