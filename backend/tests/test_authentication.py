def test_owner_login_profile_and_logout(api_client):
    client, _database_path = api_client
    client.cookies.clear()

    login = client.post(
        "/api/auth/staff/login",
        json={
            "email": "test-owner@promed.local",
            "password": "test-owner-password",
        },
    )
    assert login.status_code == 200, login.text
    assert login.json()["role"] == "owner"
    staff_cookie = login.headers["set-cookie"]
    assert "HttpOnly" in staff_cookie
    assert "Path=/api" in staff_cookie
    assert "SameSite=lax" in staff_cookie

    profile = client.get("/api/auth/staff/me")
    assert profile.status_code == 200
    assert profile.json()["role"] == "owner"

    logout = client.post("/api/auth/staff/logout", json={})
    assert logout.status_code == 204
    assert client.get("/api/auth/staff/me").json() is None


def test_invalid_staff_credentials_are_rejected(api_client):
    client, _database_path = api_client
    client.cookies.clear()

    response = client.post(
        "/api/auth/staff/login",
        json={
            "email": "test-owner@promed.local",
            "password": "incorrect-test-password",
        },
    )
    assert response.status_code == 401
