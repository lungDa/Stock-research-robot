"""Legacy behavior remains unchanged after isolated Agent execution."""
from copy import deepcopy
from fastapi.testclient import TestClient
from app.api.server import app
from app.api.agent_manager import invoke
from app.services import analysis,multifactor,freshness
from test_multifactor import annual,quote,TODAY
from test_api import A,B

def test_legacy_analysis_contract(monkeypatch):
    monkeypatch.setattr(freshness,"market_usable",lambda q:True)
    q=quote()
    q.update(eps=3,roe=.2,pe=20,yield_basis="trailing_paid_365d",**{"yield":5})
    before=deepcopy(q)
    for mode in ("income","swing"):
        assert analysis.evaluate(q,mode)==analysis.evaluate(q,mode,market_check=lambda q:True)
        assert all(v is None for v in analysis.evaluate(q,mode,market_check=lambda q:False)["checks"].values())
    assert q==before

def test_legacy_multifactor_contract(monkeypatch):
    monkeypatch.setattr(freshness,"market_usable",lambda q,today=None:True)
    q=quote();rows=annual()
    before=deepcopy((q,rows))
    assert multifactor.evaluate(q,multifactor.DEFAULT,rows,TODAY)==multifactor.evaluate(q,multifactor.DEFAULT,rows,TODAY,market_check=lambda q,today=None:True)
    assert (q,rows)==before

def test_legacy_api_survives_shadow_worker(monkeypatch):
    monkeypatch.setenv("AGENT_MANAGER_ENABLED","1")
    monkeypatch.setenv("AGENT_MANAGER_SYSTEM_MONITOR","1")
    with TestClient(app) as client:
        assert client.post("/watchlist",headers=A,json={"symbol":"AAPL"}).status_code==200
        before=client.get("/watchlist",headers=A).json()
        other=client.get("/watchlist",headers=B).json()
        result=invoke("system_monitor",{"database_ready":False,"failed_jobs":1,"stale_jobs":0})
        assert result["report"]["mode"]=="shadow"
        assert result["execution_allowed"] is False
        assert client.get("/watchlist",headers=A).json()==before
        assert client.get("/watchlist",headers=B).json()==other
        assert client.get("/health").status_code==200
        assert client.get("/admin/agents/overview",headers=A).status_code==404

import pytest
from datetime import datetime
from app.services.freshness import TAIPEI
from app.db import get
from test_recommendations import setup_job

@pytest.mark.parametrize("slot,hour,minute", [("morning",11,30),("evening",19,30)])
def test_legacy_ranking_after_shadow(monkeypatch,slot,hour,minute):
    j=setup_job(monkeypatch)
    calls=[]
    monkeypatch.setattr(j,"quota",lambda:100)
    monkeypatch.setattr(j,"push",lambda *a:calls.append(a))
    now=datetime(2026,11,10,hour,minute,tzinfo=TAIPEI)
    j.run(slot,False,now)
    key=f"recommendations:outbox:2026-11-10:{slot}:Ualice"
    before=deepcopy(get(key))
    assert before and all(x["sent"] for x in before["messages"])
    result=invoke("system_monitor",{"database_ready":False,"failed_jobs":1,"stale_jobs":0})
    assert result["report"]["mode"]=="shadow"
    assert get(key)==before
    count=len(calls)
    assert count>0
    j.run(slot,False,now)
    assert len(calls)==count
    assert get(key)==before

def test_disabled_manager_preserves_legacy_ui(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("AGENT_MANAGER_UI_ENABLED",raising=False)
    ui=AppTest.from_string("""
import streamlit as st
from app.ui.agent_manager import render
st.session_state.token="fixture"
st.session_state.agent_manager_cache={"report":"old"}
def api(*args,**kwargs):
    raise AssertionError("disabled manager called API")
st.text_input("Legacy setting",key="legacy")
render(api,True,True)
""").run()
    assert not ui.exception
    ui.text_input(key="legacy").set_value("2412").run()
    assert ui.session_state["legacy"]=="2412"
    assert "agent_manager_cache" not in ui.session_state
    assert not ui.exception


def test_refresh_and_personal_settings_survive_shadow(monkeypatch):
    from jobs import refresh_data
    from app.db import put
    from contextlib import nullcontext
    from subprocess import CompletedProcess
    c=deepcopy(multifactor.DEFAULT)
    c["stock_rules"][0]["threshold"]=4
    multifactor.save_settings("Ualice",c)
    before=[multifactor.settings_for(u) for u in ("Ualice","Ubob")]
    monkeypatch.setattr(refresh_data,"STEPS",["annual","paid"])
    monkeypatch.setattr(refresh_data,"init_db",lambda:None)
    monkeypatch.setattr(refresh_data,"leased",lambda *a:nullcontext(True))
    real_run=refresh_data.subprocess.run
    def run(args,**kwargs):
        if args[1:3]==["-m","jobs.refresh_step"]:
            if args[-1]=="annual":
                put("annual:shared:2330.TW",annual())
                snapshot=deepcopy(get("jobs:data_refresh"))
                result=invoke("system_monitor",{"database_ready":True,"failed_jobs":0,"stale_jobs":0})
                assert result["report"]["mode"]=="shadow"
                assert get("jobs:data_refresh")==snapshot
            return CompletedProcess(args,0,stdout='{"state":"finished"}',stderr="")
        return real_run(args,**kwargs)
    monkeypatch.setattr(refresh_data.subprocess,"run",run)
    result=refresh_data.run()
    assert result["state"]=="finished"
    assert get("jobs:data_refresh")==result
    assert get("annual:shared:2330.TW")==annual()
    assert [multifactor.settings_for(u) for u in ("Ualice","Ubob")]==before

def test_defensive_results_survive_shadow():
    import pandas as pd
    from app.services.defensive_model import downside_statistics,rank_candidates,BENCHMARK_WEIGHTS
    dates=pd.date_range("2025-01-01",periods=4,tz="UTC")
    market=pd.Series([-.02,-.01,.01,-.20],index=dates)
    candidates=[{"symbol":"A","eligible":True,"scores":dict.fromkeys(BENCHMARK_WEIGHTS,.95)}]
    def evaluate():
        return downside_statistics(-market,market,dates[2],1,severe_drop=.015,min_pairs=3),rank_candidates(candidates,[.99,.90,.60])
    before=evaluate()
    assert before[0]["pearson"]==pytest.approx(-1)
    assert invoke("system_monitor",{"database_ready":False,"failed_jobs":1,"stale_jobs":0})["report"]["mode"]=="shadow"
    assert evaluate()==before
