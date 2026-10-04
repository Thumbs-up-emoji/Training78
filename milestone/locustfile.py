"""Locust scenario for the protected M6 Compose API.

Run inside the VM after exporting MILESTONE5_API_KEY and MILESTONE6_JWT_TOKEN:
``locust -f locustfile.py --host=http://localhost:8000 --headless -u 10 -r 5 -t 20s --csv=evidence/locust_sanity``
``locust -f locustfile.py --host=http://localhost:8000 --headless -u 500 -r 25 -t 60s --csv=evidence/locust_500_users``
Never point the 500-user run at Cloud Run.
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task


class GovernedResearchUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        api_key = os.getenv("MILESTONE5_API_KEY")
        token = os.getenv("MILESTONE6_JWT_TOKEN")
        if not api_key or not token:
            raise RuntimeError("Set MILESTONE5_API_KEY and MILESTONE6_JWT_TOKEN before starting Locust.")
        self.headers = {"X-API-Key": api_key, "Authorization": f"Bearer {token}"}

    @task
    def governed_query(self) -> None:
        with self.client.post(
            "/query",
            json={"query": "What is our data retention policy?"},
            headers=self.headers,
            name="/query",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Unexpected status {response.status_code}")