from fastapi.testclient import TestClient
from app.api.server import app

def test_paper_routes_are_private():
    with TestClient(app) as c:
        assert c.get("/paper/account").status_code in (401, 403)
        assert c.post("/paper/account", json={}).status_code in (401, 403)
        assert c.post("/paper/orders", json={"client_order_id":"x","symbol":"2330.TW","side":"BUY","quantity":1,"price":"100"}).status_code in (401, 403)
        assert c.post("/paper/halt").status_code in (401, 403)

def test_paper_account_and_orders_are_user_scoped():
    a={"Authorization":"Bearer "+"a"*24}
    b={"Authorization":"Bearer "+"b"*24}
    with TestClient(app) as c:
        assert c.post("/paper/account",headers=a,json={}).status_code==201
        assert c.post("/paper/account",headers=b,json={}).status_code==201
        payload={"client_order_id":"unique-1","symbol":"2330.TW","side":"BUY","quantity":100,"price":"500"}
        first=c.post("/paper/orders",headers=a,json=payload)
        assert first.status_code==200,first.text
        duplicate=c.post("/paper/orders",headers=a,json=payload)
        assert duplicate.status_code==200 and duplicate.json()["duplicate"]
        assert c.get("/paper/account",headers=a).json()["positions"][0]["quantity"]==100
        assert c.get("/paper/account",headers=b).json()["positions"]==[]
        assert c.post("/paper/halt",headers=a).status_code==200
        payload["client_order_id"]="unique-2"
        assert c.post("/paper/orders",headers=a,json=payload).status_code==400
