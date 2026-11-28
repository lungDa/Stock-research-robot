from datetime import datetime
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import scheduled_reports as s
from app.services.freshness import TAIPEI

def test_scheduler_authorization_and_due_window(monkeypatch):
    app=FastAPI()
    app.include_router(s.router)
    client=TestClient(app)
    token='a'*40
    monkeypatch.delenv('REPORT_SCHEDULER_TOKEN',raising=False)
    assert client.post('/internal/scheduled-reports/watch').status_code==503
    monkeypatch.setenv('REPORT_SCHEDULER_TOKEN',token)
    assert client.post('/internal/scheduled-reports/watch').status_code==401
    headers={'Authorization':'Bearer '+token}
    monkeypatch.setattr(s,'local_now',lambda:datetime(2026,11,25,18,16,tzinfo=TAIPEI))
    assert client.post('/internal/scheduled-reports/watch',headers=headers).json()['status']=='outside_send_window'
    calls=[]
    def execute(slot):
        calls.append(slot)
        s._gate.release()
    monkeypatch.setattr(s,'execute',execute)
    monkeypatch.setattr(s,'local_now',lambda:datetime(2026,11,25,18,17,tzinfo=TAIPEI))
    assert client.post('/internal/scheduled-reports/watch',headers=headers).json()['status']=='queued'
    assert calls==['watch']
    assert client.post('/internal/scheduled-reports/evening',headers=headers).json()['status']=='outside_send_window'
    assert client.post('/internal/scheduled-reports/unknown',headers=headers).status_code==404
    with s._gate:
        assert client.post('/internal/scheduled-reports/watch',headers=headers).json()['status']=='busy'
    assert calls==['watch']
