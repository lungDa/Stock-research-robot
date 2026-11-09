"""A small foreground batch, followed by a persistent scheduled queue.
No access to personal watches; querying does not subscribe or add a watch.
"""
import os,time,re
from app.db import get,put,claim
from app.providers.market import normalize
from app.providers.annual_free import TW_DATASETS,SEC_CONCEPTS
from app.services.freshness import local_now


def feed_status(symbol):
    feeds=TW_DATASETS if symbol.endswith(('.TW','.TWO')) else SEC_CONCEPTS
    states=[get('annual:feed:'+symbol+':'+feed,{}) for feed in feeds]
    complete=sum(s.get('status')=='ok' and bool(s.get('records')) for s in states)
    return {'available_feeds':complete,'total_feeds':len(states),
            'feeds':[{'dataset':feed,'state':s.get('status','pending'),'reason':s.get('last_error',''),
                      'retry_after_seconds':max(0,round(s.get('next_attempt',0)-time.time()))}
                     for feed,s in zip(feeds,states)]}


def prepare(symbol):
    symbol=normalize(symbol);now=time.time()
    status=feed_status(symbol)
    base={'symbol':symbol,'annual_requests':0,'updated_symbols':0,'failed_feeds':0,**status}
    # No queueing until configured; never announce a download that did not start.
    tw=symbol.endswith(('.TW','.TWO'))
    if not (os.getenv('FINMIND_TOKEN','').strip() if tw else os.getenv('SEC_USER_AGENT','').strip()):
        return {**base,'state':'not_configured','message':'伺服器尚未設定'+('FINMIND_TOKEN' if tw else 'SEC_USER_AGENT')+'，本次未下載；可先顯示已有行情。'}
    if not tw and not re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+',os.getenv('SEC_USER_AGENT','')):
        return {**base,'state':'not_configured','message':'SEC_USER_AGENT須包含維護者聯絡Email，本次未下載。'}
    if not tw and ('.' in symbol or get('quote:'+symbol,{}).get('kind')=='ETF'):
        return {**base,'state':'unsupported','message':'此標的未啟用個股財報下載，保留已有行情與資料。'}
    source='finmind' if tw else 'sec'
    if now<get('annual:source:'+source,{}).get('next_attempt',0):
        return {**base,'state':'cooldown','message':'資料來源冷卻中，本次未重試，先使用已有快取。'}
    last=get('annual:query_result:'+symbol,{})
    if now-last.get('at',0)<300:
        return {**base,'state':'cached','message':'此標的剛已處理，使用共用快取；未重複下載。'}
    feeds=TW_DATASETS if tw else SEC_CONCEPTS
    if all(get('annual:feed:'+symbol+':'+feed,{}).get('status')=='ok' and
           now<get('annual:feed:'+symbol+':'+feed,{}).get('next_attempt',0) for feed in feeds):
        return {**base,'state':'cached','message':'資料集已在共用快取有效期間內，本次未重複下載。'}
    # Shared cap applies to private and public callers alike: 2/minute, 30/day.
    minute=str(int(now//60));day=str(local_now().date())
    if not any(claim('annual:query_minute:'+minute+':'+str(i),{'at':now}) for i in range(2)):
        return {**base,'state':'limited','message':'查詢下載額度暫滿，未新增請求；先顯示已有資料。'}
    if not any(claim('annual:query_day:'+day+':'+str(i),{'at':now}) for i in range(30)):
        return {**base,'state':'limited','message':'今日查詢下載額度已滿，先顯示已有資料。'}
    from app.services.data_queue import enqueue
    if not enqueue(symbol):
        return {**base,'state':'limited','message':'待補清單暫滿，保留已有資料；請稍後重試。'}
    # Reserve before starting, so a timed out browser does not immediately repeat.
    put('annual:query_result:'+symbol,{'at':now,'state':'running'})
    try:
        from jobs.refresh_annual import run
        summary=run(symbols=[symbol],max_requests=2,seconds=12,query=True) or {}
        result={**base,**summary,**feed_status(symbol)}
        if result['failed_feeds']:
            state='partial' if result['updated_symbols'] else 'failed'
            msg='本批有下載失敗項目；保留成功資料與舊快取，待排程續補。'
        elif result['annual_requests']==0:
            state='cached';msg='沒有需要重新下載的資料集，使用快取或等待冷卻結束。'
        elif result['available_feeds']<result['total_feeds']:
            state='partial';msg='本批下載已結束，已取得部分資料；其餘已加入排程續補，不需加入追蹤。'
        else:
            state='updated';msg='本批更新已完成；來源有涵蓋的資料集已取得，個別欄位仍可能缺漏。'
        result.update(state=state,message=msg)
    except Exception:
        result={**base,'state':'failed','message':'本次下載未完成，保留已有資料，已加入排程續補。'}
    put('annual:query_result:'+symbol,{'at':now,**result})
    return result


def request_download(symbol):
    """Return immediately after a bounded durable enqueue, before any HTTP call."""
    from app.db import leased
    from app.services.data_queue import enqueue
    symbol=normalize(symbol);now=time.time()
    with leased('annual:enqueue_symbol:'+symbol,15) as owned:
        if not owned:return {**status(symbol),'state':'queued','message':'此標的正在安排更新。'}
        old=get('annual:query_result:'+symbol,{})
        if now-old.get('at',0)<300:
            return {**status(symbol),'state':old.get('state','cached'),
                    'message':old.get('message','此標的剛已處理，未重複下載。')}
        tw=symbol.endswith(('.TW','.TWO'))
        eps_supported=bool(re.fullmatch(r'\d{4}\.(TW|TWO)',symbol)) and get('quote:'+symbol,{}).get('kind')!='ETF'
        configured=bool(os.getenv('FINMIND_TOKEN','').strip()) if tw else bool(
            re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+',os.getenv('SEC_USER_AGENT','')))
        if not tw and ('.' in symbol or get('quote:'+symbol,{}).get('kind')=='ETF'):
            return {**status(symbol),'state':'unsupported','message':'此標的財報來源尚未支援，保留已有行情。'}
        if not configured and not eps_supported:
            return {**status(symbol),'state':'not_configured','message':'伺服器尚未設定適用的資料來源，本次未下載。'}
        minute=str(int(now//60));day=str(local_now().date())
        if not any(claim('annual:query_minute:'+minute+':'+str(i),{'at':now}) for i in range(2)) or not any(
            claim('annual:query_day:'+day+':'+str(i),{'at':now}) for i in range(30)):
            return {**status(symbol),'state':'limited','message':'查詢下載額度暫滿，保留已有資料；待排程續補。'}
        if not enqueue(symbol):return {**status(symbol),'state':'limited','message':'待補清單暫滿，請稍後重試。'}
        result={**status(symbol),'at':now,'state':'queued','message':'已安排背景補資料，可先查看行情；完成後會在此頁提醒。'}
        put('annual:query_result:'+symbol,result)
        return result


def process_download(symbol):
    """Best-effort immediate batch; scheduled workers recover after interruption."""
    from app.db import leased
    with leased('annual:query_process:'+symbol,240) as owned:
        if not owned:return
        started=time.time()
        put('annual:query_result:'+symbol,{'at':started,'state':'running','message':'背景正在補資料，可繼續操作。'})
        try:
            from jobs.refresh_eps import run as eps_run
            from jobs.refresh_annual import run
            from jobs.refresh_tw_financials import run as official_run
            official=official_run([symbol],max_requests=2,seconds=12) if re.fullmatch(r'\d{4}\.(TW|TWO)',symbol) else {'official_requests':0}
            remaining=2-official.get('official_requests',0)
            eps=eps_run([symbol]) if remaining and re.fullmatch(r'\d{4}\.TW',symbol) else {'eps_requests':0}
            remaining-=eps.get('eps_requests',0)
            summary=(run([symbol],max_requests=remaining,seconds=12,query=True) or {}) if remaining else {}
            result={**summary,'eps_requests':eps.get('eps_requests',0),'official_requests':official.get('official_requests',0)}
            failed=summary.get('failed_feeds',0)>0 or eps.get('state')=='failed' or official.get('failed_feeds',0)>0
            state='partial' if failed or feed_status(symbol)['available_feeds']<feed_status(symbol)['total_feeds'] else 'updated'
            if summary.get('state')=='busy':state='partial'
            result.update(at=started,state=state,message='本批背景處理已結束；'+('仍有缺項，待排程續補，請查看各欄原因。' if state=='partial' else '請核對各欄期間與來源，資料集齊全不代表每個欄位都有值。'))
        except Exception:
            result={'at':started,'state':'failed','message':'本批未完成，已保留資料與待補清單，待排程續補。'}
        put('annual:query_result:'+symbol,result)


def status(symbol):
    symbol=normalize(symbol)
    last=get('annual:query_result:'+symbol,{})
    if last.get('state') in ('running','queued') and time.time()-last.get('at',0)>300:
        last={**last,'state':'partial','message':'即時批次未確認完成；待補需求仍保留，由排程續補。'}
    return {'symbol':symbol,'annual_requests':0,'updated_symbols':0,'failed_feeds':0,
            'state':'idle','message':'尚未安排下載',**last,**feed_status(symbol),
            'eps_status':get('eps:state:'+symbol,{}),
            'official_annual_status':{field:get('mopsfin:feed:'+symbol+':'+field,{}) for field in ('eps','roe_pct')},
            'official_annual_source':get('annual:source:mopsfin',{})}
