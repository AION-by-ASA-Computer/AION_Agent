import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import src.aion_env  # noqa: F401
from src.query_memory import memory
import time


import asyncio


def test_realistic_flow():
    async def _run():
        print("--- Testing Realistic Agent Flow ---")

        # 1. Define a realistic request (similar to what user asks in main.py)
        # We use a timestamp to ensure uniqueness for 'new' test cases,
        # or we can use a fixed string to test persistence across runs.
        base_request = "Qual è l'utilizzo attuale della CPU del monitoring-server?"
        request_unique = f"{base_request} [TEST-{int(time.time())}]"

        expected_query = '100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle", instance="monitoring-server"}[5m])) * 100)'

        print(f"\nUser Request: '{request_unique}'")

        # 2. STEP 1: Search in Memory
        print("\nStep 1: Searching in memory...")
        results = await memory.search(request_unique, limit=1)

        if results:
            print("CACHE HIT! Found existing query.")
            print(f"   Saved Request: {results[0]['user_request']}")
            print(f"   Saved Query:   {results[0]['promql_query']}")
        else:
            print("CACHE MISS. No matching query found.")

            # 3. Simulate Agent Work (Generation + Execution)
            print("\n Step 2: Agent generates and executes query (Simulated)...")
            print(f"   Generated PromQL: {expected_query}")

            # 4. STEP 3: Save to Memory
            print("\nStep 3: Saving successful query to memory...")
            await memory.add(request_unique, expected_query)
            print("Saved to database.")

            # 5. Verify it's now in memory
            print("\nStep 4: Verifying persistence (Search again)...")
            results_after = await memory.search(request_unique, limit=1)
            if results_after:
                print("CACHE HIT! The query was successfully recalled.")
                assert results_after[0]['promql_query'] == expected_query
            else:
                print("ERROR: Could not find query immediately after saving!")
                exit(1)

        print("\n------------------------------------------------")
        print("Test Scenario Completed Successfully")

    asyncio.run(_run())


if __name__ == "__main__":
    test_realistic_flow()
