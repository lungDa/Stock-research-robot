from app.api import agent_manager as m
from app.agents.manager_review import ReviewStore
from threading import Thread,Event
from streamlit.testing.v1 import AppTest

def test_logout_during_analysis():
    s=ReviewStore()
    session=s.begin("a","token")
    s.clear("a","token")
    assert s.record("a","token","risk",{"mode":"shadow"},{},expected=session)["status"]=="session_expired"
    assert not s.history("a","token")["runs"]

def test_duplicate_and_parallel(monkeypatch):
    entered=Event();release=Event()
    def invoke(*args):
        entered.set();release.wait(5)
        return {"mode":"shadow","status":"ok"}
    monkeypatch.setattr(m,"invoke",invoke)
    monkeypatch.setattr(m,"STORE",ReviewStore())
    t=Thread(target=m.run_once,args=("a","token","risk",{}))
    t.start()
    try:
        assert entered.wait(3)
        assert m.run_once("a","token","risk",{})["status"]=="busy"
    finally:
        release.set();t.join(6)
    assert not t.is_alive()

def test_streamlit_interaction(monkeypatch):
    monkeypatch.setenv("AGENT_MANAGER_UI_ENABLED","1")
    app=AppTest.from_string("""
import streamlit as st
from app.ui.agent_manager import render
if 'token' not in st.session_state:st.session_state.token='isolated'
def api(method,path,**kwargs):
    if path.endswith('overview'):return {'agents':[{'name':'system_monitor','enabled':True,'registered':True}]}
    return {'mode':'shadow','report':{'status':'ok'}}
render(api,True,True)
""").run()
    assert not app.exception
    app.button(key="agent_manager_overview").click().run()
    app.checkbox(key="agent_manager_enable_system_monitor").check().run()
    app.button(key="agent_manager_run").click().run()
    assert not app.exception
    assert app.session_state["agent_manager_cache"]["report"][3]["report"]["status"]=="ok"
    app.session_state["token"]="other"
    app.run()
    assert "report" not in app.session_state["agent_manager_cache"]
