import nest_asyncio
nest_asyncio.apply()

import asyncio
from ib_async import IB, Contract

def main():
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=1)
        print(f"CONNECTED! Account: {ib.managedAccounts()}")

        loop = asyncio.get_event_loop()

        # Helper to search
        def search_event_contracts(symbol, sectype, exchange, label):
            print(f"\n--- {label}: {symbol} on {exchange} ({sectype}) ---")
            try:
                results = loop.run_until_complete(
                    ib.reqSecDefOptParamsAsync(symbol, "", exchange, sectype)
                )
                print(f"  Found {len(results)} results")
                for r in results[:10]:
                    print(f"  conid={r.conid}, exchange={r.exchange}, tradingClass={r.tradingClass}, strikes={r.strikes[:5] if r.strikes else 'N/A'}")
                return results
            except Exception as e:
                print(f"  Error: {e}")
                return []

        # Helper to get contract details
        def get_contract_details(conid, label):
            print(f"\n--- Contract Details for {label} (conid={conid}) ---")
            try:
                contract = Contract()
                contract.conId = conid
                details = loop.run_until_complete(
                    ib.reqContractDetailsAsync(contract)
                )
                for d in details[:3]:
                    print(f"  {d.contract.symbol} | {d.contract.secType} | {d.contract.exchange} | right={d.contract.right} | strike={d.contract.strike} | expiry={d.contract.lastTradeDateOrContractMonth}")
                    print(f"  tradingClass={d.contract.tradingClass} | multiplier={d.contract.multiplier} | currency={d.contract.currency}")
                return details
            except Exception as e:
                print(f"  Error: {e}")
                return []

        # 1. ForecastEx - Fed Funds
        search_event_contracts("FF", "OPT", "FORECASTX", "Fed Funds ForecastEx")

        # 2. ForecastEx - CPI
        search_event_contracts("CPI", "OPT", "FORECASTX", "CPI ForecastEx")

        # 3. ForecastEx - BTC
        search_event_contracts("BTC", "OPT", "FORECASTX", "BTC ForecastEx")

        # 4. ForecastEx - ES
        search_event_contracts("ES", "OPT", "FORECASTX", "ES ForecastEx")

        # 5. CME - NQ event contracts
        search_event_contracts("NQ", "FOP", "CME", "NQ CME")

        # 6. CME - ES event contracts
        search_event_contracts("ES", "FOP", "CME", "ES CME")

        # 7. Try to get contract details for a known Fed Funds conid (from docs: 658663572)
        get_contract_details(658663572, "Fed Funds underlying")

        # 8. Check what markets are available via ForecastTrader categories
        print("\n--- Checking ForecastTrader via Web API ---")
        try:
            import requests
            # IBKR Web API is local through TWS
            # Try the local gateway
            r = requests.get("https://localhost:5006/v1/api/iserver/account", verify=False, timeout=5)
            print(f"  Web API status: {r.status_code}")
            print(f"  Response: {r.text[:200]}")
        except Exception as e:
            print(f"  Web API not available: {e}")

        ib.disconnect()
        print("\nDone. Disconnected.")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

main()
