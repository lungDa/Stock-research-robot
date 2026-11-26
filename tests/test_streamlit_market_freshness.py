import ast
from pathlib import Path
from app.services.freshness import display_market_usable


def test_display_uses_server_evidence_without_db(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("frontend must not read calendar")
    monkeypatch.setattr("app.services.freshness.taiwan_status", forbidden)
    d = {"symbol":"2330.TW","price":100,"date":"2026-11-25","freshness":{"state":"current","expected_date":"2026-11-25","actual_date":"2026-11-25"}}
    assert display_market_usable(d)
    assert not display_market_usable({**d,"data_status":"stale"})
    assert not display_market_usable({**d,"freshness":None})
    assert not display_market_usable({**d,"freshness":{**d["freshness"],"state":"calendar_missing"}})
    assert not display_market_usable({**d,"date":"2026-11-24"})
    assert not display_market_usable({**d,"price":None})


def test_streamlit_does_not_call_database_market_check():
    tree = ast.parse(Path("streamlit_app.py").read_text(encoding="utf-8"))
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="market_usable" for n in ast.walk(tree))
    assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="display_market_usable" for n in ast.walk(tree))
