"""Regression guards before adding broker execution endpoints.

These tests deliberately assert the current research-only boundary.
Remove or change the broker-route guard only in a reviewed trading feature
with explicit authorization, independent risk checks, and tests.
"""
from fastapi.testclient import TestClient

from app.api.server import app
from app.db import get
from app.services.watchlist import add, watches
from app.services.multifactor import settings_for, save_settings


def test_no_live_broker_routes_exposed():
    """Research API must not silently become an order-execution API."""
    paths = {route.path for route in app.routes}
    forbidden = ("/orders", "/broker/orders", "/trading/orders", "/trade/execute")
    assert not any(path == name or path.startswith(name + "/") for path in paths for name in forbidden)


def test_private_endpoints_require_authentication():
    with TestClient(app) as client:
        for path in ("/me", "/watchlist", "/scan", "/strategy", "/ratings",
                     "/recommendations/latest", "/admin/status"):
            assert client.get(path).status_code in (401, 403), path
        assert client.put("/strategy", json={}).status_code in (401, 403)
        assert client.post("/watchlist", json={"symbol": "2330.TW"}).status_code in (401, 403)


def test_users_have_isolated_watchlists_and_strategy_settings():
    add("Ualice", "2330.TW")
    assert "2330.TW" in watches("Ualice")
    assert "2330.TW" not in watches("Ubob")

    alice = settings_for("Ualice")
    alice["buy_score"] = 65
    save_settings("Ualice", alice)
    assert settings_for("Ualice")["buy_score"] == 65
    assert settings_for("Ubob")["buy_score"] != 65


def test_no_implicit_admin_access():
    from app.api.security import is_admin
    assert not is_admin("Ualice")
    assert not is_admin("Ubob")
