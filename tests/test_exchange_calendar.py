"""Year rollover and source-contract regressions using synthetic TWSE rows."""
import copy
from datetime import date, datetime
from unittest.mock import Mock
import pytest
from app.db import get, put
from app.providers import exchange_calendar as source, bounded_http
from app.services import market_recommendations as market
from app.services.freshness import TAIPEI
from app.services.trading_calendar import expected_close, session
from jobs import refresh_market_metadata as job


def payload(year):
    rows=[[f'{year}-01-01','中華民國開國紀念日','依規定放假1日。'],
          [f'{year}-01-04','國曆新年開始交易日','國曆新年開始交易。'],
          [f'{year}-02-01','農曆春節前最後交易日','2月2日及2月3日市場無交易。']]
    rows += [[f'{year}-02-{d:02}','市場無交易，僅辦理結算交割作業',''] for d in range(2,6)]
    rows += [[f'{year}-12-25','行憲紀念日','依規定放假1日。']]
    return {'stat':'ok','date':f'{year}0101','queryYear':year,
            'title':f'{year-1911} 年市場開休市日期','fields':['日期','名稱','說明'],
            'total':len(rows),'data':rows}


def test_year_pinned_source_and_last_session_description(monkeypatch):
    fetch=Mock(return_value=payload(2026))
    monkeypatch.setattr(bounded_http,'fetch_json',fetch)
    row=market.calendar(2026)
    fetch.assert_called_once_with(source.URL,{'date':'20260101','response':'json'},max_bytes=65536,seconds=12,socket_timeout=(8,3))
    assert '2026-02-01' in row['opened'] and '2026-02-01' not in row['closed']
    assert '2026-02-02' in row['closed']
    assert get('recommendations:calendar:2027') is None
    assert market.calendar(2026)==row
    assert fetch.call_count==1


@pytest.mark.parametrize('fault',['year','date','title','row_year','fields','total','short_row','empty','duplicate','conflict'])
def test_rejected_payload_never_overwrites_verified_year(monkeypatch,fault):
    good={**source.parse(payload(2026),2026),'at':1}
    put('recommendations:calendar:2026',good)
    bad=payload(2026)
    if fault=='year':bad['queryYear']=2027
    elif fault=='date':bad['date']='20270101'
    elif fault=='title':bad['title']='116 年市場開休市日期'
    elif fault=='row_year':bad['data'][0][0]='2027-01-01'
    elif fault=='fields':bad['fields'][0]='日期異動'
    elif fault=='total':bad['total']+=1
    elif fault=='short_row':bad['data'][0].pop()
    elif fault=='empty':bad['data']=[];bad['total']=0
    else:
        extra=copy.deepcopy(bad['data'][0])
        if fault=='conflict':extra[1]='開始交易日'
        bad['data'].append(extra);bad['total']+=1
    monkeypatch.setattr(bounded_http,'fetch_json',lambda *a,**k:bad)
    with pytest.raises(ValueError):market.calendar(2026)
    assert get('recommendations:calendar:2026')==good


def test_legacy_openapi_cache_is_replaced_even_when_recent(monkeypatch):
    import time
    old={**source.parse(payload(2026),2026),'at':time.time()}
    old.pop('source')
    put('recommendations:calendar:2026',old)
    fetch=Mock(return_value=payload(2026));monkeypatch.setattr(bounded_http,'fetch_json',fetch)
    assert market.calendar(2026)['source']==source.URL
    assert fetch.call_count==1


def test_january_cold_start_fetches_prior_year_for_both_readers(monkeypatch):
    monkeypatch.setattr(job,'local_now',lambda:datetime(2027,1,1,19,tzinfo=TAIPEI))
    requests=[]
    def fetch(url,params,**kw):
        requests.append(params['date'])
        return payload(int(params['date'][:4]))
    monkeypatch.setattr(bounded_http,'fetch_json',fetch)
    result=job.run()
    assert result['state']=='finished' and requests==['20270101','20260101']
    assert market.target_day(date(2027,1,4),'morning')==date(2026,12,31)
    assert expected_close(datetime(2027,1,1,19,tzinfo=TAIPEI),get)==date(2026,12,31)
    # Trading-calendar reads never cause another request.
    assert len(requests)==2


def test_november_rollover_prefetch_and_optional_failure(monkeypatch):
    monkeypatch.setattr(job,'local_now',lambda:datetime(2026,11,19,tzinfo=TAIPEI))
    def fetch(url,params,**kw):
        year=int(params['date'][:4])
        return payload(2026 if year==2027 else year)  # Upstream has not published next year.
    monkeypatch.setattr(bounded_http,'fetch_json',fetch)
    result=job.run()
    assert result['state']=='finished' and result['optional_years']==[2027]
    assert result['years']['2027']['state']=='failed'
    assert get('recommendations:calendar:2027') is None
    monkeypatch.setattr(bounded_http,'fetch_json',lambda url,params,**kw:payload(int(params['date'][:4])))
    assert job.run()['years']['2027']['state']=='finished'


def test_missing_required_year_is_partial_but_other_years_continue(monkeypatch):
    monkeypatch.setattr(job,'local_now',lambda:datetime(2027,1,1,19,tzinfo=TAIPEI))
    def fetch(url,params,**kw):
        year=int(params['date'][:4])
        if year==2026:raise TimeoutError('source timeout')
        return payload(year)
    monkeypatch.setattr(bounded_http,'fetch_json',fetch)
    result=job.run()
    assert result['state']=='partial' and result['years']['2027']['state']=='finished'
    assert expected_close(datetime(2027,1,1,19,tzinfo=TAIPEI),get) is None


def test_bad_override_and_conflicting_cache_never_become_open(monkeypatch):
    put('recommendations:session_overrides',{'2026-11-19':'false'})
    with pytest.raises(RuntimeError):market.is_session(date(2026,11,19))
    put('recommendations:session_overrides',{})
    row=source.parse(payload(2026),2026)
    row['opened'].append(row['closed'][0])
    put('recommendations:calendar:2026',row)
    assert session(date(2026,11,19),get) is None
