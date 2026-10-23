import httpx

from tests.conftest import REGISTER, signup

API = "/api/v1"


async def test_register_normalises_and_hides_secrets(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{API}/auth/register", json={**REGISTER, "email": "Asha@Example.com"})
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "asha@example.com"
    assert body["country"] == "IN" and body["llm_mode"] == "mock"
    assert "password_hash" not in body and "llm_api_key_encrypted" not in body


async def test_duplicate_email_conflicts(client: httpx.AsyncClient) -> None:
    await client.post(f"{API}/auth/register", json=REGISTER)
    r = await client.post(f"{API}/auth/register", json={**REGISTER, "email": "ASHA@example.com"})
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_register_validation(client: httpx.AsyncClient) -> None:
    for bad in (
        {"password": "short"},
        {"base_currency": "XYZ"},
        {"timezone": "Mars/Base"},
        {"country": "IND"},
        {"unexpected": "field"},
    ):
        r = await client.post(f"{API}/auth/register", json={**REGISTER, **bad})
        assert r.status_code == 422, bad
        assert r.json()["errors"]


async def test_login_failure_is_generic(client: httpx.AsyncClient) -> None:
    await client.post(f"{API}/auth/register", json=REGISTER)
    wrong = await client.post(
        f"{API}/auth/login", json={"email": REGISTER["email"], "password": "nope-nope-nope"}
    )
    missing = await client.post(
        f"{API}/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"}
    )
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json()["detail"] == missing.json()["detail"]


async def test_protected_routes_require_valid_token(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{API}/me")).status_code == 401
    bad = await client.get(f"{API}/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401


async def test_refresh_rotation_and_reuse_detection(client: httpx.AsyncClient) -> None:
    await signup(client)
    first = client.cookies.get("sw_refresh")
    assert first

    r = await client.post(f"{API}/auth/refresh")
    assert r.status_code == 200 and r.json()["access_token"]
    second = client.cookies.get("sw_refresh")
    assert second and second != first

    # Replaying the rotated token revokes the whole family, including the newest token.
    client.cookies.set("sw_refresh", first, path="/api/v1/auth")
    assert (await client.post(f"{API}/auth/refresh")).status_code == 401
    client.cookies.set("sw_refresh", second, path="/api/v1/auth")
    assert (await client.post(f"{API}/auth/refresh")).status_code == 401


async def test_logout_revokes_refresh(client: httpx.AsyncClient) -> None:
    await signup(client)
    token = client.cookies.get("sw_refresh")
    assert (await client.post(f"{API}/auth/logout")).status_code == 204
    client.cookies.set("sw_refresh", token, path="/api/v1/auth")
    assert (await client.post(f"{API}/auth/refresh")).status_code == 401
    client.cookies.clear()
    assert (await client.post(f"{API}/auth/refresh")).status_code == 401


async def test_change_password(client: httpx.AsyncClient) -> None:
    headers = await signup(client)
    r = await client.post(
        f"{API}/auth/password",
        json={"current_password": "wrong-password", "new_password": "another-long-pass"},
        headers=headers,
    )
    assert r.status_code == 401
    r = await client.post(
        f"{API}/auth/password",
        json={"current_password": REGISTER["password"], "new_password": "another-long-pass"},
        headers=headers,
    )
    assert r.status_code == 204
    assert (await client.post(f"{API}/auth/refresh")).status_code == 401
    ok = await client.post(
        f"{API}/auth/login", json={"email": REGISTER["email"], "password": "another-long-pass"}
    )
    assert ok.status_code == 200


async def test_health_and_request_id(client: httpx.AsyncClient) -> None:
    r = await client.get("/healthz", headers={"X-Request-ID": "abc12345-test"})
    assert r.json() == {"status": "ok"}
    assert r.headers["x-request-id"] == "abc12345-test"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert (await client.get("/readyz")).json()["database"] == "up"
