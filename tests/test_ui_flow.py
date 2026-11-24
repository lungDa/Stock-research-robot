from pathlib import Path
from unittest.mock import Mock
from streamlit.testing.v1 import AppTest
from app.services.multifactor import rated
from tests.test_improvements import quote


def test_transient_auth_failure_keeps_session_and_offers_retry(monkeypatch):
    import requests
    maintenance=Mock(status_code=200)
    maintenance.json.return_value={'maintenance':False}
    monkeypatch.setattr(requests,'get',lambda *a,**k:maintenance)
    def offline(*a,**k):raise requests.Timeout('private upstream details')
    monkeypatch.setattr(requests,'request',offline)
    app=AppTest.from_file(str(Path(__file__).parents[1]/'streamlit_app.py'),default_timeout=20)
    app.session_state['token']='a'*24
    app.session_state['browser_logout_pending']=False
    app.run()
    assert not app.exception
    assert app.session_state['token']=='a'*24
    assert app.session_state['browser_logout_pending'] is False
    assert app.button(key='retry_login')
    assert not any('private upstream' in e.value for e in app.error)


def test_unreachable_maintenance_does_not_claim_scheduled_maintenance(monkeypatch):
    import requests
    def offline(*a,**k):raise requests.ConnectionError('private connection')
    monkeypatch.setattr(requests,'get',offline)
    app=AppTest.from_file(str(Path(__file__).parents[1]/'streamlit_app.py'),default_timeout=20)
    app.run()
    assert not app.exception
    assert app.button(key='retry_service')
    assert any('無法確認服務狀態' in w.value for w in app.warning)


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
    # The UI now probes maintenance before rendering forms. Stub this
    # separate GET request explicitly; keep production fail-closed behavior.
    maintenance=Mock(status_code=200)
    maintenance.json.return_value={'maintenance':False}
    monkeypatch.setattr(requests,'get',lambda url,**kwargs: maintenance)
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
        elif url.endswith('/coverage/summary'):body={'universe':{'verified':False},'three_field_diagnostic':{'fresh':False},'note':'尚待核對'}
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
    # The UI now probes maintenance before rendering forms. Stub this
    # separate GET request explicitly; keep production fail-closed behavior.
    maintenance=Mock(status_code=200)
    maintenance.json.return_value={'maintenance':False}
    monkeypatch.setattr(requests,'get',lambda url,**kwargs: maintenance)
    app=AppTest.from_file(str(Path(__file__).parents[1]/'streamlit_app.py'),default_timeout=20)
    app.session_state['token']='a'*24
    app.run();assert not app.exception
    app.button(key='FormSubmitter:ttm_components_form-驗證算式並儲存我的TTM EPS').click().run()
    assert not app.exception and any('/ttm-eps-components/' in url for _,url in calls)
    assert any('請確認' in error.value for error in app.error)


def test_defensive_research_displays_coverage_and_missing_publication():
    app = AppTest.from_string("""
import streamlit as st
from app.ui.defensive_research import render
def api(method, path, **kwargs):
    assert not st.session_state.get('requested')
    st.session_state['requested'] = True
    assert path == '/defensive/research/2330.TW'
    assert kwargs['params'] == {'severe_drop': .02}
    return {'state': 'evaluated', 'symbol': '2330.TW', 'as_of': '2026-11-24',
            'severe_drop': .02, 'min_pairs': 60, 'benchmarks': {
                'tw_electronics': {'periods': {'1': {
                    'status': 'available', 'paired_coverage': .8, 'pairs': 80,
                    'expected_sessions': 100, 'down_sessions': 20, 'severe_sessions': 4,
                    'up_probability': 0}}},
                'nasdaq_100': {'state': 'publication_times_missing'},
            }}
render(api, True)
""").run()
    assert not app.exception and not app.dataframe
    app.button[0].click().run()
    assert not app.exception
    rows = app.dataframe[0].value
    assert rows.iloc[0]['資料涵蓋率'] == '80.0%'
    assert rows.iloc[0]['逆勢上漲機率'] == '0.0%'
    assert rows.iloc[3]['狀態'] == '缺少逐日公布時間'
    assert rows.iloc[3]['逆勢上漲機率'] == '—'
    app.selectbox[0].select(3).run()
    assert not app.exception
    assert app.subheader[0].value.endswith('近 3 年')


def test_defensive_market_view_reuses_snapshot_and_reports_missing_benchmarks():
    app = AppTest.from_string("""
import streamlit as st
from app.ui.defensive_research import render_market_ranking
def api(method, path):
    assert (method, path) == ('GET', '/defensive/market-ranking')
    assert not st.session_state.get('requested')
    st.session_state['requested'] = True
    rank = {'relaxation_tier': 1, 'eligible': 6, 'matched': 1,
            'items': [{'symbol': '2317.TW', 'score': .58}]}
    return {'state': 'evaluated', 'as_of': '2026-11-24', 'generated_at': '2026-11-24T19:00:00+08:00',
            'coverage': {'current_history': 6, 'universe': 10}, 'thresholds': [.6, .55, .5],
            'min_pairs': 60, 'min_down_sessions': 20,
            'benchmark_status': {'tw_electronics': {'state': 'evaluated'},
                                 'nasdaq_100': {'state': 'publication_times_missing'}},
            'periods': {str(year): {'combined': rank, 'tw_electronics': rank,
                                    'nasdaq_100': rank} for year in (1, 3, 5)}}
render_market_ranking(api, True)
""").run()
    assert not app.exception and not app.dataframe
    app.button(key='load_defensive_market').click().run()
    assert not app.exception and not app.dataframe
    assert any('綜合榜仍缺少可用基準' in item.value for item in app.info)
    app.selectbox(key='defensive_market_benchmark').select('tw_electronics').run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]['逆勢上漲命中率'] == '58.0%'
    assert any('命中率門檻 55%' in item.value for item in app.caption)
    app.selectbox(key='defensive_market_period').select(3).run()
    assert not app.exception and app.dataframe
    app.selectbox(key='defensive_market_benchmark').select('nasdaq_100').run()
    assert not app.exception and not app.dataframe
    assert any('缺少逐日公布時間' in item.value for item in app.info)


def test_defensive_swing_view_shows_empty_study_without_zero_returns():
    app = AppTest.from_string("""
import streamlit as st
from app.ui.defensive_research import render_swing
def api(method, path, **kwargs):
    assert path == '/defensive/swing/2330.TW'
    assert kwargs['params'] == {'holding': 'true'}
    summary = {'count': 0, 'win_rate': None, 'mean_return': None,
               'cumulative_return': None, 'mean_holding_sessions': None}
    trials = {str(days): {'summary': summary, 'trades': [], 'limitations': []}
              for days in (10, 20, 30)}
    return {'state': 'evaluated', 'symbol': '2330.TW', 'label': '觀望',
            'as_of': '2026-11-24', 'risk_level': None, 'verified_risk_sessions': 0,
            'entry_signals': 0, 'backtests': {str(year): trials for year in (1, 3, 5)},
            'limitations': ['缺歷史風險紀錄']}
render_swing(api, True)
""").run()
    app.checkbox[0].check()
    app.button[0].click().run()
    assert not app.exception
    rows = app.dataframe[0].value
    assert list(rows['固定持有期']) == [10, 20, 30]
    assert list(rows['勝率']) == ['—', '—', '—']
    assert any('風險 缺資料' in item.value for item in app.caption)
