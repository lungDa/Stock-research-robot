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


def run(symbols=None,max_requests=4,seconds=24):
    init_db();start=time.monotonic();now=time.time();count=0;touched=set();failed=0
    max_requests=max(1,min(int(max_requests),4));seconds=max(1,min(float(seconds),24))
    with leased('annual:worker',180) as owned:
        if not owned:return {'state':'busy','official_requests':0}
        if symbols is None:
            symbols=list(requested())+[s for u in member_users() for s in watches(u)]
            symbols+=[s.strip() for s in os.getenv('ANNUAL_SYMBOLS','').split(',') if s.strip()]
        symbols=sorted({normalize(s) for s in symbols if s.strip()})
        symbols=[s for s in symbols if re.fullmatch(r'\d{4}\.(TW|TWO)',s) and get('quote:'+s,{}).get('kind')!='ETF']
        def download(path,**kwargs):
            nonlocal count
            if count>=max_requests or time.monotonic()-start>=seconds:raise StopIteration
            if not source_slot('mopsfin',48):raise StopIteration
            count+=1
            return request(path,**kwargs)
        if not symbols:return {'state':'idle','official_requests':0}
        source=get('annual:source:mopsfin',{})
        if now<source.get('next_attempt',0):return {'state':'cooldown','official_requests':0}
        catalog=get('mopsfin:catalog',{})
        try:
            if now-catalog.get('at',0)>7*86400 or not catalog.get('metrics'):
                catalog={'at':now,'metrics':parse_catalog(download('/'))}
                put('mopsfin:catalog',catalog)
        except StopIteration:return {'state':'limited','official_requests':count}
        except Exception as exc:
            put('annual:source:mopsfin',{'next_attempt':now+86400,**describe(exc,'官方目錄')})
            result={'state':'failed','official_requests':count,'failed_feeds':1,'updated_at':datetime.now(timezone.utc).isoformat()}
            put('jobs:tw_financials',result)
            return result
        tasks=[(symbol,field) for field in ('eps','roe_pct') for symbol in symbols]
        cursor_key='mopsfin:cursor' if len(symbols)>1 else 'mopsfin:cursor:'+symbols[0]
        cursor=get(cursor_key,{'value':0})['value']%len(tasks)
        for offset in range(len(tasks)):
            if count>=max_requests or time.monotonic()-start>=seconds:break
            i=(cursor+offset)%len(tasks);symbol,field=tasks[i];key='mopsfin:feed:'+symbol+':'+field
            state=get(key,{})
            if now<state.get('next_attempt',0):continue
            put(cursor_key,{'value':i})  # Resume this task if metadata uses the last request.
            stage='公司代號查詢'
            try:
                company=get('mopsfin:company:'+symbol,{})
                if now-company.get('at',0)>30*86400 or not company.get('display'):
                    company={'at':now,'display':parse_company(download('/suggestCompany',params={'query':symbol.split('.')[0]}),symbol)}
                    put('mopsfin:company:'+symbol,company)
                metric=catalog['metrics'][field]
                stage='年度'+field+'下載'
                payload=download('/compare/data',form=annual_fields(field,company['display'],metric))
                stage='年度'+field+'解析'
                rows=parse_annual(payload,symbol,field,company['display'],local_now().date(),metric)
                shared=copy.deepcopy(get('financial:official:'+symbol,{'rows':{}}))
                for year,row in rows.items():
                    current=shared['rows'].setdefault(year,{})
                    sources={**current.get('field_sources',{}),**row['field_sources']}
                    current.update(row);current['field_sources']=sources
                shared.update(updated_at=datetime.now(timezone.utc).isoformat(),status='partial',company_display=company['display'])
                put('financial:official:'+symbol,shared)
                put(key,{'status':'ok','at':now,'years':sorted(rows),'next_attempt':now+7*86400})
                put(cursor_key,{'value':(i+1)%len(tasks)})
                touched.add(symbol)
            except StopIteration:break
            except Exception as exc:
                failed+=1
                code=getattr(getattr(exc,'response',None),'status_code',None)
                detail=describe(exc,stage)
                put(key,{**state,'status':'failed','last_attempt':now,**detail,'next_attempt':now+86400})
                put(cursor_key,{'value':(i+1)%len(tasks)})
                if code in (401,403,429):
                    put('annual:source:mopsfin',{'next_attempt':now+86400,**detail});break
        result={'state':'partial' if failed else 'finished','official_requests':count,
                'updated_symbols':len(touched),'failed_feeds':failed,'updated_at':datetime.now(timezone.utc).isoformat()}
        put('jobs:tw_financials',result)
        return result


if __name__=='__main__':print(run())
