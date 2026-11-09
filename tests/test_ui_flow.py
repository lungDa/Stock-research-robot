from pathlib import Path
from unittest.mock import Mock
from streamlit.testing.v1 import AppTest
from app.services.multifactor import rated
from tests.test_improvements import quote


def test_query_shows_quote_before_enqueue_and_refreshes_after_background(monkeypatch):
    import requests
    calls=[]
    data=rated(quote(),'public')
    def request(method,url,**kwargs):
        calls.append((method,url))
        if '/quote/' in url:body=data
        elif '/fundamentals/request/' in url:body={'state':'queued','symbol':'2330.TW','message':'已開始背景更新','available_feeds':0,'total_feeds':5}
        elif '/fundamentals/status/' in url:body={'state':'partial','message':'本批已結束，仍待補','available_feeds':2,'total_feeds':5,'feeds':[]}
        elif url.endswith('/scan'):body={}
        else:raise AssertionError('Unexpected request '+url)
        response=Mock(status_code=200);response.json.return_value=body;return response
    monkeypatch.setattr(requests,'request',request)
    app=AppTest.from_file(str(Path(__file__).parents[1]/'streamlit_app.py'),default_timeout=20)
    app.run()
    assert not app.exception
    app.button(key='FormSubmitter:query-分析').click().run()
    assert not app.exception
    query_calls=[(method,url) for method,url in calls if '/quote/' in url or '/fundamentals/' in url]
    assert '/public/quote/' in query_calls[0][1]
    assert query_calls[1][0]=='POST' and '/public/fundamentals/request/' in query_calls[1][1]
    assert any('/public/fundamentals/status/' in url for _,url in query_calls)
    assert sum('/public/quote/' in url for _,url in query_calls)==2
    assert app.session_state['download_pending'] is False
    assert app.session_state['download_notice_key']=='已提醒'
    assert any('基本面' in exp.label or '缺漏原因' in exp.label for exp in app.expander)
