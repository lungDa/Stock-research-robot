"""Small resumable official annual EPS/ROE batches, without a paid data token."""
import os,re,time,copy
from datetime import datetime,timezone
from app.db import init_db,get,put,leased
from app.services.data_queue import requested,source_slot
from app.services.accounts import member_users
from app.services.watchlist import watches
from app.services.freshness import local_now
from app.providers.market import normalize
from app.providers.mopsfin import request,parse_catalog,parse_company,parse_annual,annual_fields
from app.providers.source_errors import describe


def failure_detail(exc,stage):
    # Stages are code-owned literals; never include symbols, users, URLs or payloads.
    if stage.endswith(('讀取','寫入')):
        return {'stage':stage,'error_code':'storage','reason':stage+'：資料庫操作失敗'}
    return describe(exc,stage)


def run(symbols=None,max_requests=4,seconds=24):
    started=time.monotonic();init_db();start=time.monotonic();now=time.time();count=0;touched=set();failed=0
    failures=[]
    stop_reason=None;scanned=0;skipped=0;total=0;preparation_seconds=0
    max_requests=max(1,min(int(max_requests),4));seconds=max(1,min(float(seconds),24))
    def finish(state,reason=None,persist=True):
        result={'state':state,'official_requests':count,'updated_symbols':len(touched),
                'failed_feeds':failed,'failures':failures,'stop_reason':reason,
                'total_tasks':total,'scanned_tasks':scanned,'skipped_feed_cooldown':skipped,
                'db_init_seconds':round(start-started,3),'preparation_seconds':round(preparation_seconds,3),
                'elapsed_budget_seconds':round(time.monotonic()-start,3),'budget_seconds':seconds,
                'updated_at':datetime.now(timezone.utc).isoformat()}
        if persist:put('jobs:tw_financials',result)
        return result
    def budget_limit():
        nonlocal stop_reason
        if count>=max_requests:stop_reason='request_limit'
        elif time.monotonic()-start>=seconds:stop_reason='time_limit'
        else:return False
        return True
    with leased('annual:worker',180) as owned:
        if not owned:return finish('busy','worker_busy',persist=False)
        if symbols is None:
            symbols=list(requested())+[s for u in member_users() for s in watches(u)]
            symbols+=[s.strip() for s in os.getenv('ANNUAL_SYMBOLS','').split(',') if s.strip()]
        symbols=sorted({normalize(s) for s in symbols if s.strip()})
        symbols=[s for s in symbols if re.fullmatch(r'\d{4}\.(TW|TWO)',s) and get('quote:'+s,{}).get('kind')!='ETF']
        def download(path,**kwargs):
            nonlocal count,stop_reason
            if budget_limit():raise StopIteration
            if not source_slot('mopsfin',48):
                stop_reason='source_quota';raise StopIteration
            # Reserving a slot also accesses the DB; do not start a request after
            # that wait consumes the time budget. Never refund a shared slot.
            if budget_limit():raise StopIteration
            count+=1
            return request(path,**kwargs)
        total=2*len(symbols)
        preparation_seconds=time.monotonic()-start
        if not symbols:return finish('idle','no_symbols')
        source=get('annual:source:mopsfin',{})
        if now<source.get('next_attempt',0):return finish('cooldown','source_cooldown')
        catalog=get('mopsfin:catalog',{})
        preparation_seconds=time.monotonic()-start
        stage='官方目錄下載'
        try:
            if now-catalog.get('at',0)>7*86400 or not catalog.get('metrics'):
                payload=download('/')
                stage='官方目錄解析'
                catalog={'at':now,'metrics':parse_catalog(payload)}
                stage='官方目錄寫入'
                put('mopsfin:catalog',catalog)
        except StopIteration:return finish('limited',stop_reason)
        except Exception as exc:
            detail=failure_detail(exc,stage)
            put('annual:source:mopsfin',{'next_attempt':now+86400,**detail})
            failed=1;failures.append(detail)
            return finish('failed','catalog_failure')
        tasks=[(symbol,field) for field in ('eps','roe_pct') for symbol in symbols]
        cursor_key='mopsfin:cursor' if len(symbols)>1 else 'mopsfin:cursor:'+symbols[0]
        cursor=get(cursor_key,{'value':0})['value']%len(tasks)
        for offset in range(len(tasks)):
            if budget_limit():break
            i=(cursor+offset)%len(tasks);symbol,field=tasks[i];key='mopsfin:feed:'+symbol+':'+field
            state=get(key,{})
            scanned+=1
            if now<state.get('next_attempt',0):
                skipped+=1;continue
            put(cursor_key,{'value':i})  # Resume this task if metadata uses the last request.
            stage='公司快取讀取'
            try:
                company=get('mopsfin:company:'+symbol,{})
                if now-company.get('at',0)>30*86400 or not company.get('display'):
                    stage='公司代號下載'
                    payload=download('/suggestCompany',params={'query':symbol.split('.')[0]})
                    stage='公司代號解析'
                    company={'at':now,'display':parse_company(payload,symbol)}
                    stage='公司快取寫入'
                    put('mopsfin:company:'+symbol,company)
                stage='年度'+field+'請求準備'
                metric=catalog['metrics'][field]
                form=annual_fields(field,company['display'],metric)
                stage='年度'+field+'下載'
                payload=download('/compare/data',form=form)
                stage='年度'+field+'解析'
                rows=parse_annual(payload,symbol,field,company['display'],local_now().date(),metric)
                stage='年度'+field+'快取讀取'
                shared=copy.deepcopy(get('financial:official:'+symbol,{'rows':{}}))
                stage='年度'+field+'資料整合'
                for year,row in rows.items():
                    current=shared['rows'].setdefault(year,{})
                    sources={**current.get('field_sources',{}),**row['field_sources']}
                    current.update(row);current['field_sources']=sources
                shared.update(updated_at=datetime.now(timezone.utc).isoformat(),status='partial',company_display=company['display'])
                stage='年度'+field+'寫入'
                put('financial:official:'+symbol,shared)
                put(key,{'status':'ok','at':now,'years':sorted(rows),'next_attempt':now+7*86400})
                put(cursor_key,{'value':(i+1)%len(tasks)})
                touched.add(symbol)
            except StopIteration:break
            except Exception as exc:
                failed+=1
                detail=failure_detail(exc,stage)
                # Bound log size even for cached metadata failures without requests.
                if len(failures)<4:failures.append(detail)
                put(key,{**state,'status':'failed','last_attempt':now,**detail,'next_attempt':now+86400})
                put(cursor_key,{'value':(i+1)%len(tasks)})
                if detail['error_code'] in ('http_401','http_403','http_429'):
                    put('annual:source:mopsfin',{'next_attempt':now+86400,**detail})
                    stop_reason='source_cooldown';break
        if failed:return finish('partial',stop_reason or 'feed_failure')
        if stop_reason:return finish('limited',stop_reason)
        if skipped==total:return finish('cooldown','feed_cooldown')
        return finish('finished','tasks_scanned')


if __name__=='__main__':
    from jobs.tw_financial_summary import write_summary
    result=run()
    write_summary({'result':result})
    print(result)
