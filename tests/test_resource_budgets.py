import json
import time
from unittest.mock import Mock
import pytest
from app.providers import bounded_http as http
from app.providers import taiwan_official as official

class Response:
    status_code=200
    headers={}
    def __init__(self,chunks): self.chunks=chunks
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def raise_for_status(self): pass
    def iter_content(self,size): yield from self.chunks

def fake(monkeypatch,chunks):
    loader=Mock(return_value=Response(chunks))
    monkeypatch.setattr(http.requests,'get',loader)
    return loader

def test_array_cap_preserves_only_complete_records(monkeypatch):
    body=b'[{"Code":"2330"},{"Code":"2412"}]'
    fake(monkeypatch,[body])
    r=http.fetch_json('https://example.com',max_bytes=20,array=True)
    assert r['records']==[{'Code':'2330'}] and not r['complete']

def test_normal_json_cap_does_not_parse_truncated_response(monkeypatch):
    fake(monkeypatch,[b'{"data":"' + b'x'*100+b'"}'])
    with pytest.raises(http.ResourceLimitError):http.fetch_json('https://example.com',max_bytes=30)

def test_complete_array_reports_complete(monkeypatch):
    fake(monkeypatch,[b'[{"Code":"2330"}]'])
    assert http.fetch_json('https://example.com',array=True)['complete']

def test_utf8_boundaries_preserved(monkeypatch):
    raw=json.dumps([{'Name':'台積電'}],ensure_ascii=False).encode()
    fake(monkeypatch,[raw[:11],raw[11:12],raw[12:]])
    assert http.fetch_json('https://example.com',array=True)['records'][0]['Name']=='台積電'

def test_time_budget_returns_partial_records(monkeypatch):
    fake(monkeypatch,[b'[{"Code":"2330"},',b'{"Code":"2412"}]'])
    ticks=iter([0,0,10]);monkeypatch.setattr(http.time,'monotonic',lambda:next(ticks))
    result=http.fetch_json('https://example.com',seconds=6,array=True)
    assert result['records']==[{'Code':'2330'}] and result['reason']=='時間預算'

def test_socket_timeouts_and_redirects(monkeypatch):
    loader=fake(monkeypatch,[b'{}'])
    http.fetch_json('https://example.com')
    assert loader.call_args.kwargs['timeout']==(2,2)
    assert loader.call_args.kwargs['allow_redirects'] is False

def test_warning_is_not_repeated_for_every_symbol(monkeypatch):
    monkeypatch.setattr(official,'_warning_until',{})
    logger=Mock();monkeypatch.setattr(official,'log',logger)
    official.warn_once('same','warn');official.warn_once('same','warn')
    assert logger.warning.call_count==1

def test_catalog_never_downloads_large_html(monkeypatch):
    request=Mock(side_effect=AssertionError('must not download'))
    monkeypatch.setattr(official,'_request',request)
    assert official.catalog('TW')=={} and request.call_count==0

def test_scan_limit_and_report_do_not_walk_whole_universe(monkeypatch):
    import jobs.scan as scan
    from app.db import put,get
    symbols=[f'{i:04d}.TW' for i in range(1000,2000)]
    monkeypatch.setattr(scan,'load',lambda:symbols)
    calls=[]
    def research(symbol,refresh):
        calls.append(symbol)
        put('quote:'+symbol,{'symbol':symbol,'cached_at':time.time(),'name':'test','date':'2026-11-06','income':{'matched':False},'swing':{'matched':False}})
    monkeypatch.setattr(scan,'research',research)
    scan.run(10000,10000)
    report=get('scan:latest')
    assert len(calls)==30 and report['attempted']==30 and report['budget_seconds']==120
    assert get('scan:cursor')['cursor']==30

def test_failed_scan_does_not_overwrite_previous_report(monkeypatch):
    import jobs.scan as scan
    from app.db import put,get
    put('scan:latest',{'previous':True})
    monkeypatch.setattr(scan,'load',lambda:['2330.TW'])
    monkeypatch.setattr(scan,'research',Mock(side_effect=RuntimeError('offline')))
    with pytest.raises(RuntimeError):scan.run(1,30)
    assert get('scan:latest')=={'previous':True}
