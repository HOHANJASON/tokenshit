import os
import time

import httpx


BASE = os.getenv("NEXTOKEN_TEST_BASE", "http://127.0.0.1:3100")
ADMIN_PASSWORD = os.getenv("NEXTOKEN_TEST_ADMIN_PASSWORD", "test-admin-password")
MOCK_PROVIDER_BASE = os.getenv("NEXTOKEN_TEST_PROVIDER_BASE", "http://127.0.0.1:3200/v1")
FAILING_PROVIDER_BASE = os.getenv("NEXTOKEN_TEST_FAILING_PROVIDER_BASE", "http://127.0.0.1:3201/v1")


def check(response):
    response.raise_for_status()
    return response.json()


def main():
    suffix = str(int(time.time()))
    with httpx.Client(base_url=BASE, timeout=20) as client:
        admin = check(client.post("/api/admin/login", json={"username": "admin", "password": ADMIN_PASSWORD}))["token"]
        ah = {"Authorization": f"Bearer {admin}"}
        provider_id = check(
            client.post(
                "/api/admin/providers",
                headers=ah,
                json={"name": f"Mock Provider {suffix}", "base_url": MOCK_PROVIDER_BASE, "api_key": "mock-secret", "priority": 1, "active": True},
            )
        )["id"]
        provider_test = check(client.post(f"/api/admin/providers/{provider_id}/test", headers=ah))
        assert provider_test["ok"] is True
        public_model = f"mock-gpt-{suffix}"
        check(
            client.post(
                "/api/admin/models",
                headers=ah,
                json={
                    "public_name": public_model,
                    "upstream_model": "mock-gpt",
                    "provider_id": provider_id,
                    "input_cost": 5,
                    "output_cost": 30,
                    "input_price": 8,
                    "output_price": 48,
                    "active": True,
                },
            )
        )
        customer_token = check(client.post("/api/customer/register", json={"email": f"test-{suffix}@example.com", "password": "strong-test-password"}))["token"]
        ch = {"Authorization": f"Bearer {customer_token}"}
        customer = check(client.get("/api/customer/me", headers=ch))
        created_key = check(client.post("/api/customer/keys", headers=ch, json={"name": "Smoke Test"}))
        raw_key = created_key["api_key"]
        check(client.patch(f"/api/admin/keys/{created_key['id']}/limits", headers=ah, json={"rpm_limit": 3, "tpm_limit": 100000}))
        check(client.post("/api/admin/topup", headers=ah, json={"customer_id": customer["id"], "amount": 10, "note": "Smoke test"}))
        failing_provider_id = check(
            client.post(
                "/api/admin/providers",
                headers=ah,
                json={"name": f"Failing Provider {suffix}", "base_url": FAILING_PROVIDER_BASE, "api_key": "mock-secret", "priority": 0, "active": True},
            )
        )["id"]
        model_id = next(row["id"] for row in check(client.get("/api/admin/models", headers=ah)) if row["public_name"] == public_model)
        check(
            client.post(
                f"/api/admin/models/{model_id}/routes",
                headers=ah,
                json={"provider_id": failing_provider_id, "upstream_model": "mock-gpt", "input_cost": 5, "output_cost": 30, "priority": 0, "weight": 100, "active": True},
            )
        )
        completion = check(
            client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"model": public_model, "messages": [{"role": "user", "content": "Hello"}]},
            )
        )
        assert completion["choices"][0]["message"]["content"] == "NexToken proxy works."
        after = check(client.get("/api/customer/me", headers=ch))
        assert abs(after["balance"] - 9.968) < 0.000001
        usage = check(client.get("/api/customer/usage", headers=ch))
        assert usage[0]["input_tokens"] == 1000
        assert usage[0]["output_tokens"] == 500
        assert abs(usage[0]["charge"] - 0.032) < 0.000001
        routes = check(client.get(f"/api/admin/models/{model_id}/routes", headers=ah))
        assert next(row for row in routes if row["provider_id"] == failing_provider_id)["failure_count"] == 1
        with client.stream(
            "POST",
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={"model": public_model, "messages": [{"role": "user", "content": "Stream"}], "stream": True},
        ) as stream_response:
            stream_response.raise_for_status()
            streamed = "".join(stream_response.iter_text())
        assert "NexToken stream works." in streamed
        after_stream = check(client.get("/api/customer/me", headers=ch))
        assert abs(after_stream["balance"] - 9.936) < 0.000001
        image_model = f"mock-image-{suffix}"
        check(
            client.post(
                "/api/admin/models",
                headers=ah,
                json={
                    "public_name": image_model,
                    "upstream_model": "mock-image",
                    "provider_id": provider_id,
                    "input_cost": 0,
                    "output_cost": 0,
                    "input_price": 0,
                    "output_price": 0,
                    "endpoint_type": "image",
                    "unit_cost": 0.02,
                    "unit_price": 0.05,
                    "active": True,
                },
            )
        )
        image = check(
            client.post(
                "/v1/images/generations",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"model": image_model, "prompt": "A test image", "n": 2},
            )
        )
        assert image["data"][0]["b64_json"] == "aW1hZ2U="
        after_image = check(client.get("/api/customer/me", headers=ch))
        assert abs(after_image["balance"] - 9.836) < 0.000001
        catalog = check(client.get("/api/catalog"))
        assert catalog["count"] == 31
        assert sum(row["endpoint_type"] == "image" for row in catalog["data"]) == 3
        limited = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={"model": public_model, "messages": [{"role": "user", "content": "Rate limit"}]},
        )
        assert limited.status_code == 429
        assert "Retry-After" in limited.headers
        pricing = check(client.get("/api/pricing"))
        assert any(row["model_name"] == public_model for row in pricing["data"])
        low_token = check(client.post("/api/customer/register", json={"email": f"low-{suffix}@example.com", "password": "strong-test-password"}))["token"]
        low_headers = {"Authorization": f"Bearer {low_token}"}
        low_customer = check(client.get("/api/customer/me", headers=low_headers))
        low_key = check(client.post("/api/customer/keys", headers=low_headers, json={"name": "Low Balance"}))["api_key"]
        check(client.post("/api/admin/topup", headers=ah, json={"customer_id": low_customer["id"], "amount": 0.01, "note": "Reserve test"}))
        low_response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {low_key}"},
            json={"model": public_model, "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 4096},
        )
        assert low_response.status_code == 402
        print("SMOKE_TEST_OK", {"model": public_model, "balance": after["balance"], "charge": usage[0]["charge"]})


if __name__ == "__main__":
    main()
