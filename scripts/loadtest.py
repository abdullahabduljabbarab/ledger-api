"""
Load test harness for the Ledger API.

Run against the live GCP deployment:
    locust -f scripts/loadtest.py --host https://ledger-api-465847189589.europe-west2.run.app

Then open http://localhost:8089 to configure users and start the test.
"""

import uuid

from locust import HttpUser, between, task


class LedgerUser(HttpUser):
    wait_time = between(0.1, 0.5)
    account_id = None
    auth_headers = None

    def on_start(self):
        resp = self.client.post("/auth/token", data={
            "username": "admin",
            "password": "admin123",
        })
        token = resp.json()["access_token"]
        self.auth_headers = {"Authorization": f"Bearer {token}"}

        name = f"load-{uuid.uuid4().hex[:8]}"
        resp = self.client.post(
            "/accounts",
            json={"name": name},
            headers=self.auth_headers,
        )
        self.account_id = resp.json()["id"]

        self.client.post("/transactions", json={
            "idempotency_key": f"seed-{uuid.uuid4().hex}",
            "type": "deposit",
            "amount": "10000.00",
            "account_id": self.account_id,
        }, headers=self.auth_headers)

    @task(3)
    def deposit(self):
        self.client.post("/transactions", json={
            "idempotency_key": uuid.uuid4().hex,
            "type": "deposit",
            "amount": "10.00",
            "account_id": self.account_id,
        }, headers=self.auth_headers)

    @task(2)
    def withdraw(self):
        self.client.post("/transactions", json={
            "idempotency_key": uuid.uuid4().hex,
            "type": "withdrawal",
            "amount": "5.00",
            "account_id": self.account_id,
        }, headers=self.auth_headers)

    @task(3)
    def check_balance(self):
        self.client.get(
            f"/accounts/{self.account_id}/balance",
            headers=self.auth_headers,
        )

    @task(1)
    def list_entries(self):
        self.client.get(
            f"/accounts/{self.account_id}/entries?limit=10",
            headers=self.auth_headers,
        )

    @task(1)
    def idempotent_retry(self):
        key = uuid.uuid4().hex
        payload = {
            "idempotency_key": key,
            "type": "deposit",
            "amount": "1.00",
            "account_id": self.account_id,
        }
        self.client.post(
            "/transactions", json=payload, headers=self.auth_headers,
        )
        self.client.post(
            "/transactions", json=payload, headers=self.auth_headers,
        )

    @task(1)
    def health(self):
        self.client.get("/health")
