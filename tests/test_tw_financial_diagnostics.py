"""Offline regression coverage for the diagnostics emitted into Actions logs."""
import json
import time
from unittest.mock import Mock

import pytest
import requests

from app.db import get,put
from jobs import refresh_tw_financials as job
from tests.test_mopsfin import CATALOG,DISPLAY,payload,seed_metadata


SECRET='token=private-token user@example.test postgres://private-password'


@pytest.mark.parametrize('exc,code',[
    (requests.ReadTimeout(SECRET),'timeout'),
    (requests.ConnectionError(SECRET),'connection'),
    (json.JSONDecodeError(SECRET,SECRET,0),'json'),
    (ValueError(SECRET),'contract'),
    *[(requests.HTTPError(SECRET,response=Mock(status_code=status)),f'http_{status}')
      for status in (401,403,429,'429',503)],
])
def test_one_request_failure_is_visible_and_safe(monkeypatch,exc,code):
    seed_metadata()
    original={'rows':{'2025':{'eps':7}}}
    put('financial:official:6488.TWO',original)
    loader=Mock(side_effect=exc);monkeypatch.setattr(job,'request',loader)
    result=job.run(['6488.TWO'],max_requests=1)
    assert result['state']=='partial'
    assert (result['official_requests'],result['failed_feeds'],result['updated_symbols'])==(1,1,0)
    detail=result['failures'][0]
    assert detail['stage']=='年度eps下載' and detail['error_code']==code
    assert get('jobs:tw_financials')==result
    assert get('financial:official:6488.TWO')==original
    assert get('mopsfin:feed:6488.TWO:eps')['next_attempt']>time.time()
    assert get('mopsfin:cursor:6488.TWO')['value']==1
    assert SECRET not in json.dumps(result)
    assert 'private-token' not in str(get('mopsfin:feed:6488.TWO:eps'))
    # No symbol/watchlist or company identity is added to public job diagnostics.
    assert '6488' not in str(detail) and DISPLAY not in str(detail)
    assert '6488.TWO' not in str(result) and DISPLAY not in str(result)
    if code in ('http_401','http_403','http_429'):
        assert job.run(['6488.TWO'])['state']=='cooldown'
        assert loader.call_count==1


@pytest.mark.parametrize('route,body,stage',[
    ('/',requests.ReadTimeout(SECRET),'官方目錄下載'),
    ('/','<html>private-token</html>','官方目錄解析'),
    ('/suggestCompany',requests.ReadTimeout(SECRET),'公司代號下載'),
    ('/suggestCompany',{'suggestions':['wrong private-token']},'公司代號解析'),
    ('/compare/data',{'ylabel':'wrong private-token'},'年度eps解析'),
])
def test_download_and_parse_stages_are_distinct(monkeypatch,route,body,stage):
    if route!='/':
        put('mopsfin:catalog',{'at':time.time(),'metrics':job.parse_catalog(CATALOG)})
    if route=='/compare/data':seed_metadata()
    def load(path,**kwargs):
        assert path==route
        if isinstance(body,Exception):raise body
        return body
    monkeypatch.setattr(job,'request',load)
    result=job.run(['6488.TWO'],max_requests=1)
    assert result['failures'][0]['stage']==stage
    assert result['failed_feeds']==1 and result['updated_symbols']==0
    assert 'private-token' not in str(result)
    assert get('financial:official:6488.TWO') is None


def test_storage_failure_is_not_misreported_as_parse_failure(monkeypatch):
    seed_metadata()
    monkeypatch.setattr(job,'request',Mock(return_value=payload()))
    real_put=job.put
    def fail_write(key,value):
        if key=='financial:official:6488.TWO':raise RuntimeError(SECRET)
        return real_put(key,value)
    monkeypatch.setattr(job,'put',fail_write)
    result=job.run(['6488.TWO'],max_requests=1)
    assert result['failures'][0]['stage']=='年度eps寫入'
    assert result['failures'][0]['error_code']=='storage'
    assert result['updated_symbols']==0 and SECRET not in str(result)


def test_one_failed_metric_does_not_discard_successful_metric(monkeypatch):
    seed_metadata()
    put('financial:official:6488.TWO',{'rows':{'2025':{'eps':7}}})
    monkeypatch.setattr(job,'request',Mock(side_effect=[
        requests.ReadTimeout(SECRET),payload('roe_pct')]))
    result=job.run(['6488.TWO'],max_requests=2)
    assert result['state']=='partial' and result['updated_symbols']==1
    assert result['failed_feeds']==1 and len(result['failures'])==1
    row=get('financial:official:6488.TWO')['rows']['2025']
    assert row['eps']==7 and row['roe_pct']==4.5


def test_cached_metric_failure_is_preparation_and_samples_are_bounded(monkeypatch):
    symbols=[f'{code}.TW' for code in range(2000,2004)]
    put('mopsfin:catalog',{'at':time.time(),'metrics':{'unexpected':'private-token'}})
    for symbol in symbols:
        put('mopsfin:company:'+symbol,{'at':time.time(),'display':symbol[:4]+' Company'})
    loader=Mock();monkeypatch.setattr(job,'request',loader)
    result=job.run(symbols)
    assert result['failed_feeds']==8 and len(result['failures'])==4
    assert result['official_requests']==0
    assert all(d['stage']=='年度eps請求準備' for d in result['failures'])
    loader.assert_not_called()
    assert 'private-token' not in str(result)


def test_budget_exhaustion_is_not_a_feed_failure_and_resumes(monkeypatch):
    monkeypatch.setattr(job,'request',Mock(return_value=CATALOG))
    result=job.run(['6488.TWO'],max_requests=1)
    assert result['failures']==[] and result['failed_feeds']==0
    assert get('mopsfin:feed:6488.TWO:eps') is None
    monkeypatch.setattr(job,'request',Mock(return_value={'suggestions':[DISPLAY]}))
    result=job.run(['6488.TWO'],max_requests=1)
    assert result['failures']==[] and result['failed_feeds']==0
    assert get('mopsfin:cursor:6488.TWO')['value']==0
    monkeypatch.setattr(job,'request',Mock(return_value=payload()))
    result=job.run(['6488.TWO'],max_requests=1)
    assert result['updated_symbols']==1 and result['failures']==[]


def test_refresh_summary_retains_safe_diagnostics(monkeypatch):
    import subprocess
    from jobs import refresh_data
    seed_metadata()
    monkeypatch.setattr(job,'request',Mock(side_effect=requests.ReadTimeout(SECRET)))
    result=job.run(['6488.TWO'],max_requests=1)
    monkeypatch.setattr(refresh_data,'STEPS',['tw_financials'])
    monkeypatch.setattr(refresh_data.subprocess,'run',Mock(return_value=
        subprocess.CompletedProcess([],0,stdout=json.dumps(result)+'\n',stderr='')))
    summary=refresh_data.run()
    assert summary['state']=='partial'
    assert summary['steps']['tw_financials']['result']['failures']==result['failures']
    assert SECRET not in str(summary)
