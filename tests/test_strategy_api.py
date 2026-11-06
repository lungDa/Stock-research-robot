import copy
from fastapi.testclient import TestClient
from app.api.server import app
from app.services.multifactor import DEFAULT
from tests.test_multifactor import csv_text
A={'Authorization':'Bearer '+'a'*24}
B={'Authorization':'Bearer '+'b'*24}

def test_strategy_auth_persistence_isolation_and_invalid():
    with TestClient(app) as c:
        assert c.get('/strategy').status_code==401
        config=c.get('/strategy',headers=A).json()
        config['daily_cap']=2
        assert c.put('/strategy',headers=A,json=config).status_code==200
        assert c.get('/strategy',headers=A).json()['daily_cap']==2
        assert c.get('/strategy',headers=B).json()['daily_cap']==3
        config['stock_rules']=[]
        assert c.put('/strategy',headers=A,json=config).status_code==400
        assert c.get('/strategy',headers=A).json()['daily_cap']==2

def test_annual_upload_validation_and_body_limit():
    with TestClient(app) as c:
        text=csv_text([{'year':2025,'eps':3,'source_url':'https://example.com/report'}])
        assert c.post('/annual/2330',headers=A,content=text).status_code==200
        assert c.post('/annual/2330',headers=A,content='x'*131073).status_code==413
        assert c.post('/annual/2330',headers=A,content='bad').status_code==400
        assert c.post('/annual/2330',content=text).status_code==401
