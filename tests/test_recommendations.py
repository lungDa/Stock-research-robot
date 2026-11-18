import copy,time
from datetime import date,datetime,timedelta
import pytest
from app.db import get,put
from app.services import market_recommendations as m
from app.services.multifactor import DEFAULT,rule
from app.services.freshness import TAIPEI

DAY=date(2026,11,10)
pytestmark=pytest.mark.usefixtures('taiwan_market')

@pytest.fixture(autouse=True)
def morning_clock(taiwan_market,monkeypatch):
    monkeypatch.setattr('app.services.freshness.local_now',lambda:datetime(2026,11,10,11,30,tzinfo=TAIPEI))
def config():
    c=copy.deepcopy(DEFAULT);c['stock_rules']=[rule('eps_latest',1,1)];return c

def item(symbol='2412.TW',eps=2):
    return ({'symbol':symbol,'name':symbol,'kind':'STOCK','price':100,'date':'2026-11-09','data_status':'partial','currency':'TWD'}, {'2025':{'eps':eps}})

def test_strict_matches_are_not_padded_with_relaxed_candidates():
    c=config()
    items=[item(f'{1000+i}.TW', 1.2 if i<3 else .85) for i in range(12)]
    r=m.rank(items,c,DAY)
    assert len(r['items'])==3 and r['matched']==3 and r['round']==0
    assert all(d['relaxation_round']==0 for d in r['items'])
    assert {d['symbol'] for d in r['items']}=={'1000.TW','1001.TW','1002.TW'}


def test_only_relax_when_zero_and_never_mutate():
    c=config();old=copy.deepcopy(c)
    r=m.rank([item(eps=1.01),item('2330.TW',.95)],c,DAY)
    assert r['round']==0 and r['matched']==1
    assert r['items'][0]['symbol']=='2412.TW'
    r=m.rank([item(eps=.95)],c,DAY)
    assert r['round']==1 and r['matched']==1 and r['items'][0]['relaxation_round']==1
    assert c==old


def test_first_successful_relaxed_round_is_not_padded():
    r=m.rank([item(eps=.95),item('2330.TW',.85)],config(),DAY)
    assert r['round']==1 and r['matched']==1
    assert [d['symbol'] for d in r['items']]==['2412.TW']
    assert r['rules'][0]['threshold']==.9


def test_later_relaxed_round_scans_all_candidates_before_top_ten():
    items=[item(f'{n:04}.TW',eps=.85) for n in range(1031,1010,-1)]
    r=m.rank(items,config(),DAY)
    assert r['round']==2 and r['matched']==21 and len(r['items'])==10
    assert r['items'][0]['symbol']=='1011.TW'
    assert all(d['relaxation_round']==2 for d in r['items'])


@pytest.mark.parametrize('eps,round_',[(2,0),(.95,1),(.7,3)])
def test_summary_describes_zero_match_relaxation(eps,round_):
    report={**m.rank([item(eps=eps)],config(),DAY),
            'coverage':{'universe':1,'stock_quotes':1},'slot_label':'11:30',
            'target_date':'2026-11-09','universe_partial':False}
    text=m.messages(report)[0]
    assert report['round']==round_
    assert '為補足前10名' not in text
    assert ('原條件零檔符合' in text)==bool(round_)
    if not report['items']:assert '目前無可推薦個股' in text

def test_three_rounds_no_padding_missing_and_boolean_guards():
    assert m.rank([item(eps=.7)],config(),DAY)['round']==3
    assert not m.rank([item(eps=.7)],config(),DAY)['items']
    c=config();c['missing_policy']='available'
    d,rows=item();rows['2025']['eps']=None
    r=m.rank([(d,rows)],c,DAY)
    assert r['round']==3 and not r['items'] and r['eligible']==0
    c['stock_rules'] += [rule('fcf_positive',1,1,'=='),rule('fcf_coverage',1,1,'>=')]
    assert m.relaxed(c,3)['stock_rules'][1:]==c['stock_rules'][1:]

def test_top_ten_deterministic_excludes_nonstocks():
    items=[item(f'{n:04}.TW') for n in range(31,10,-1)]
    d,rows=item('0050.TW');d['kind']='ETF';items.append((d,rows))
    r=m.rank(items,config(),DAY)
    assert len(r['items'])==10 and r['matched']==21
    assert r['items'][0]['symbol']=='0011.TW'

def test_calendar_holiday_and_previous_session(monkeypatch):
    monkeypatch.setattr(m,'calendar',lambda year:{'year':year,'closed':['2026-11-09'],'opened':[]})
    assert not m.is_session(date(2026,11,9))
    assert m.target_day(DAY,'morning')==date(2026,11,6)
    assert m.target_day(DAY,'evening')==DAY
    put('recommendations:session_overrides',{'2026-11-10':False})
    assert not m.is_session(DAY)

def test_calendar_contract(monkeypatch):
    from app.providers import bounded_http
    monkeypatch.setattr(m,'local_now',lambda:datetime(2026,11,10,tzinfo=TAIPEI))
    rows=[[f'2026-01-{d:02}','依規定放假',''] for d in range(1,6)]
    rows += [['2026-01-06','開始交易日','開始交易']]
    payload={'stat':'ok','date':'20260101','queryYear':2026,'title':'115 年市場開休市日期',
             'fields':['日期','名稱','說明'],'data':rows,'total':len(rows)}
    monkeypatch.setattr(bounded_http,'fetch_json',lambda *a,**kw:payload)
    assert m.calendar(2026)['opened']==['2026-01-06']
    with pytest.raises(ValueError,match='年度不符'):m.calendar(2024)

def test_collect_visits_beyond_thirty_and_personal_isolation():
    symbols=[f'{n:04}.TW' for n in range(1000,1041)]
    index={s[:4]:{'fields':{'kind':{'value':'STOCK'}}} for s in symbols}
    put('fundamentals:index:TW',index)
    snapshots={'TW':{s[:4]:{'date':'2026-11-09','close':100,'name':s} for s in symbols}}
    put('annual:Ualice:'+symbols[-1],{'2025':{'eps':9}})
    items,stats=m.collect(symbols,snapshots,date(2026,11,9),'Ualice',time.monotonic()+10)
    assert stats['stock_quotes']==41 and items[-1][1]['2025']['eps']==9
    bob,_=m.collect(symbols,snapshots,date(2026,11,9),'Ubob',time.monotonic()+10)
    assert not bob[-1][1]
    snapshots['TW'][symbols[0][:4]]['date']='2026-11-10'
    _,stats=m.collect(symbols,snapshots,date(2026,11,9),'Ualice',time.monotonic()+10)
    assert stats['stock_quotes']==40

def test_outbox_stable_retry_and_no_duplicate(monkeypatch):
    from jobs import recommend as j
    calls=[]
    def push(user,text,key):
        calls.append((user,text,key))
        if len(calls)==2:raise TimeoutError('uncertain')
    monkeypatch.setattr(j,'push',push)
    with pytest.raises(TimeoutError):j.deliver('Ualice','out',['summary','stock'],False,100)
    j.deliver('Ualice','out',['changed content'],False,100)
    assert calls[1]==calls[2] and len(calls)==3
    j.deliver('Ualice','out',[],False,100)
    assert len(calls)==3
    j.deliver('Ualice','preview',['x'],True,0);assert get('preview') is None

def test_quota_never_creates_outbox_when_insufficient():
    from jobs import recommend as j
    with pytest.raises(RuntimeError):j.deliver('Ualice','out',['x'],False,5)
    assert get('out') is None

def setup_job(monkeypatch):
    from jobs import recommend as j
    from app.providers import taiwan_official,universe
    from jobs import refresh_universe
    monkeypatch.setattr(j,'is_session',lambda day:True)
    monkeypatch.setattr(j,'member_users',lambda:['Ualice','Ubob'])
    monkeypatch.setattr(j,'can_use_personal',lambda u:True)
    m.enable('Ualice',True)
    monkeypatch.setattr(j,'target_day',lambda today,slot:date(2026,11,9) if slot=='morning' else today)
    monkeypatch.setattr(refresh_universe,'build',lambda:None)
    monkeypatch.setattr(universe,'load',lambda:['2412.TW','6488.TWO'])
    monkeypatch.setattr(taiwan_official,'snapshot',lambda market:{'2412' if market=='TW' else '6488':{'date':'2026-11-09','close':100,'name':'stock'},'_meta':{'complete':True}})
    monkeypatch.setattr(j,'collect',lambda *a:([item()],{'universe':2,'stock_quotes':2}))
    monkeypatch.setattr(j,'settings_for',lambda user:config())
    return j

def test_run_subscriber_slot_preview_no_push(monkeypatch):
    j=setup_job(monkeypatch)
    monkeypatch.setattr(j,'quota',lambda:pytest.fail('preview quota call'))
    monkeypatch.setattr(j,'push',lambda *a:pytest.fail('preview push'))
    r=j.run('morning',now=datetime(2026,11,10,11,30,tzinfo=TAIPEI))
    assert r['status']=='preview' and len(r['reports'])==1
    report=get('recommendations:preview:Ualice')
    assert report['target_date']=='2026-11-09' and not get('recommendations:latest:Ubob')
    assert len(m.messages(report))==2
    with pytest.raises(RuntimeError):j.run('evening',now=datetime(2026,11,10,19,30,tzinfo=TAIPEI))

def test_job_send_idempotent_and_outside_window(monkeypatch):
    j=setup_job(monkeypatch);calls=[]
    monkeypatch.setattr(j,'quota',lambda:100)
    monkeypatch.setattr(j,'push',lambda *a:calls.append(a))
    now=datetime(2026,11,10,11,30,tzinfo=TAIPEI)
    j.run('morning',False,now);j.run('morning',False,now)
    assert len(calls)==2
    with pytest.raises(RuntimeError):j.run('morning',False,now.replace(hour=13))


@pytest.mark.parametrize('main_sent',[False,True])
@pytest.mark.parametrize('four_pending',[False,True])
def test_four_report_recovers_independently_of_existing_main_outbox(monkeypatch,main_sent,four_pending):
    from app.day_trader import reporting
    j=setup_job(monkeypatch)
    now=datetime(2026,11,10,11,30,tzinfo=TAIPEI)
    main_key='recommendations:outbox:2026-11-10:morning:Ualice'
    four_key='four_rankings:outbox:2026-11-10:morning:Ualice'
    put(main_key,{'created_at':time.time(),'messages':[
        {'text':'saved main','retry_key':'main-retry','sent':main_sent}]})
    if four_pending:
        put(four_key,{'created_at':time.time(),'messages':[
            {'text':'saved four','retry_key':'four-retry','sent':False}]})
    monkeypatch.setattr(reporting,'preferences',lambda u:{'enabled':u=='Ualice'})
    refreshed=[]
    def refresh(user,day):
        refreshed.append((user,day))
        return {'as_of':day,'rankings':{'long_term':[{'symbol':'2330.TW'}]}}
    monkeypatch.setattr(reporting,'refresh_cached',refresh)
    monkeypatch.setattr(reporting,'summary',lambda report:'new four')
    monkeypatch.setattr(j,'collect',lambda *a:pytest.fail('must resume the saved main report'))
    monkeypatch.setattr(j,'quota',lambda:100)
    calls=[]
    monkeypatch.setattr(j,'push',lambda *a:calls.append(a))
    j.run('morning',False,now)
    j.run('morning',False,now)
    four_text='saved four' if four_pending else 'new four'
    assert sum(call[1]==four_text for call in calls)==1
    assert sum(call[1]=='saved main' for call in calls)==(0 if main_sent else 1)
    if four_pending:
        assert calls[0]==('Ualice','saved four','four-retry')
        assert refreshed==[]
    else:
        assert refreshed==[('Ualice','2026-11-09')]
    assert all(entry['sent'] for key in (main_key,four_key) for entry in get(key)['messages'])

def test_preferences_api_and_line_commands():
    from fastapi.testclient import TestClient
    from app.api.server import app
    from app.channels.commands import handle
    client=TestClient(app);headers={'Authorization':'Bearer '+'a'*24}
    assert client.get('/recommendations/preferences').status_code==401
    assert client.put('/recommendations/preferences',headers=headers,json={'enabled':True}).json()['enabled']
    assert not m.preferences('Ubob')['enabled']
    assert '關閉' in handle('Ualice','排名通知關閉')
    assert '開啟' in handle('Ualice','排名通知開啟')
    handle('Ualice','通知關閉');assert not m.preferences('Ualice')['enabled']

def test_deadline_stops_without_partial_market_result():
    with pytest.raises(TimeoutError):m.collect(['2412.TW'],{},DAY,'Ualice',time.monotonic()-1)

def test_required_missing_cannot_pass_even_when_other_rules_score_high():
    c=config();c['missing_policy']='available';c['stock_rules'].append(rule('roe_avg',15,1,weight=1))
    assert not m.rank([item()],c,DAY)['items']

def test_relax_upward_for_upper_bound_and_streak_rounding():
    c=config();c['stock_rules']=[rule('price_ma20',10,1,'<'),rule('dividend_streak',10,10,'>=')]
    r=m.relaxed(c,1)
    assert r['stock_rules'][0]['threshold']>10 and r['stock_rules'][1]['threshold']==9

