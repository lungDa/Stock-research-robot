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


def test_personal_financial_proof_form_renders_and_rejects_empty_input(monkeypatch):
    import requests
    from app.services.multifactor import DEFAULT
    from app.services.assistant import DEFAULT as ASSISTANT_DEFAULT
    calls=[]
    def request(method,url,**kwargs):
        calls.append((method,url))
        if url.endswith('/auth/me'):body={'stage':'active','name':'測試','password_change_required':False,'is_admin':False}
        elif url.endswith('/admin/bootstrap/status'):body={'designated':False,'initialized':False}
        elif url.endswith('/auth/devices'):body={'devices':[]}
        elif url.endswith('/watchlist'):body=[]
        elif url.endswith('/strategy'):body=DEFAULT
        elif url.endswith('/assistant/preferences'):body=ASSISTANT_DEFAULT
        elif url.endswith('/recommendations/preferences'):body={'enabled':False}
        elif url.endswith('/four-rankings/preferences'):body={'enabled':False}
        elif url.endswith('/scan'):body={}
        elif '/ttm-eps-components/' in url:
            from app.services.ttm_proof import calculate
            response=Mock(status_code=400)
            try:calculate(kwargs['json'])
            except ValueError as exc:response.json.return_value={'detail':str(exc)}
            else:raise AssertionError('Empty proof must fail validation')
            return response
        else:raise AssertionError('Unexpected request '+url)
        response=Mock(status_code=200);response.json.return_value=body;return response
    monkeypatch.setattr(requests,'request',request)
    app=AppTest.from_file(str(Path(__file__).parents[1]/'streamlit_app.py'),default_timeout=20)
    app.session_state['token']='a'*24
    app.run();assert not app.exception
    app.button(key='FormSubmitter:ttm_components_form-驗證算式並儲存我的TTM EPS').click().run()
    assert not app.exception and any('/ttm-eps-components/' in url for _,url in calls)
    assert any('請確認' in error.value for error in app.error)
