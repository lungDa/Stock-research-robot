"""Bounded annual cash-dividend backfill for every known TW/TWO common stock."""
import os,re,time,copy
from datetime import datetime,timezone
from app.db import init_db,get,put,leased
from app.providers.market import normalize
from app.providers.mopsfin import request
from app.providers.cashflow_report import catalog,fields,parse
from app.providers.source_errors import describe
from app.services.freshness import local_now
from app.services.data_queue import requested,source_slot
from app.services.accounts import member_users
from app.services.watchlist import watches


def universe():
    rows=[];complete=True
    for market in ('TW','TWO'):
        state=get('universe:small:'+market,{})
        complete=complete and bool(state.get('complete'))
        rows += [row['symbol'] for row in state.get('rows',[]) if isinstance(row,dict) and row.get('symbol')]
    # Never call the repository's demonstration CSV a full-market universe.
    return sorted({s for s in rows if re.fullmatch(r'\d{4}\.(TW|TWO)',s)}),complete


def run(symbols=None,max_requests=2,years=5):
    init_db();now=time.time();today=local_now().date();count=0;updated=0;failures=0;missing=0;missing_reasons={}
    max_requests=max(1,min(int(max_requests),4));years=max(1,min(int(years),15))
    requested_years=list(range(today.year-1,max(2012,today.year-years-1),-1))
    explicit=symbols is not None
    with leased('annual:worker',75) as owned:
        if not owned:return {'state':'busy','cash_requests':0}
        if explicit:
            priority=sorted({normalize(s) for s in symbols if s.strip()});market=[];complete=False
        else:
            priority=list(dict.fromkeys(list(requested())+[s for u in member_users() for s in watches(u)]+
                [normalize(s) for s in os.getenv('ANNUAL_SYMBOLS','').split(',') if s.strip()]))
            market,complete=universe()
            for user in member_users():
                from app.services.multifactor import settings_for
                rules=settings_for(user).get('stock_rules',[])
                years=max([years]+[r['years'] for r in rules if r.get('enabled') and r.get('metric')=='fcf_coverage'])
            requested_years=list(range(today.year-1,max(2012,today.year-years-1),-1))
        # Classification is read in bounded batches below, rather than one SQL
        # round trip per stock in the market universe.
        from app.db import get_many
        kinds={};all_symbols=list(dict.fromkeys(priority+market))
        for offset in range(0,len(all_symbols),80):kinds.update(get_many(['quote:'+s for s in all_symbols[offset:offset+80]]))
        priority=[s for s in priority if re.fullmatch(r'\d{4}\.(TW|TWO)',s) and kinds.get('quote:'+s,{}).get('kind')!='ETF']
        market=[s for s in market if s not in priority and kinds.get('quote:'+s,{}).get('kind')!='ETF']
        summary={'cash_requests':0,'updated_fields':0,'failed_feeds':0,'market_symbols':len(market)+len(priority),
            'market_complete':complete,'years':requested_years,'scope':'全台股母體分批輪替；優先查詢／追蹤標的；不代表已下載齊全'}
        if not priority and not market:return {**summary,'state':'idle'}
        if now<get('annual:source:mopsfin',{}).get('next_attempt',0):return {**summary,'state':'cooldown'}
        # Start the HTTP budget after expensive universe/classification reads.
        start=time.monotonic()
        def download(path,**kwargs):
            nonlocal count
            if count>=max_requests or time.monotonic()-start>=35 or not source_slot('mopsfin',48):raise StopIteration
            count+=1;return request(path,**kwargs)
        metric=get('cashflow:catalog',{})
        catalog_state=get('cashflow:catalog_state',{})
        if catalog_state.get('parser_version')==2 and now<catalog_state.get('next_attempt',0):return {**summary,'state':'cooldown','reason':catalog_state.get('reason','')}
        try:
            if now-metric.get('at',0)>7*86400 or not metric.get('metric'):
                metric={'at':now,'metric':catalog(download('/'))};put('cashflow:catalog',metric)
                put('cashflow:catalog_state',{'next_attempt':0})
        except StopIteration:return {**summary,'state':'limited','cash_requests':count}
        except Exception as exc:
            detail=describe(exc,'現金流量表目錄')
            put('cashflow:catalog_state',{'next_attempt':now+3600,'parser_version':2,**detail})
            code=getattr(getattr(exc,'response',None),'status_code',None)
            if code in (401,403,429):put('annual:source:mopsfin',{'next_attempt':now+86400,**detail})
            result={**summary,'state':'failed','cash_requests':count,'failed_feeds':1,'reason':detail['reason']}
            put('jobs:cash_dividends',result);return result
        year_cursor=get('cashflow:year_cursor',{}).get('value',0)%len(requested_years)
        batch_size=max(1,min(20,get('cashflow:batch_size',{}).get('value',20)))
        for offset in range(len(requested_years)):
            if count>=max_requests or time.monotonic()-start>=35:break
            slot=(year_cursor+offset)%len(requested_years);year=requested_years[slot]
            candidates=[]
            groups=[('priority',priority,batch_size if not market else max(1,batch_size//2)),('market',market,batch_size)]
            if batch_size==1 and priority and market:
                turn=get('cashflow:single_turn',{}).get('value',0)%2
                if turn:groups.reverse()
                put('cashflow:single_turn',{'value':1-turn})
            for group,pool,cap in groups:
                if len(candidates)>=batch_size:break
                if not pool:continue
                cursor_key=f'cashflow:cursor:{group}:{year}'
                cursor=get(cursor_key,{}).get('value',0)%len(pool)
                page=[pool[(cursor+n)%len(pool)] for n in range(min(len(pool),80))]
                keys=[key for s in page for key in (f'cashflow:state:{s}:{year}','annual:shared:'+s)]
                records={}
                for at in range(0,len(keys),80):records.update(get_many(keys[at:at+80]))
                checked=0;chosen=0
                for symbol in page:
                    checked+=1
                    state=records.get(f'cashflow:state:{symbol}:{year}',{})
                    known=records.get('annual:shared:'+symbol,{}).get('rows',{}).get(str(year),{}).get('cash_dividends_paid')
                    # A value alone is not a verified annual paid-dividend total.
                    # Require source, unit, full-year period and explicit basis.
                    shared_row=records.get('annual:shared:'+symbol,{}).get('rows',{}).get(str(year),{})
                    proof=(shared_row.get('field_sources') or {}).get('cash_dividends_paid') or {}
                    verified=(type(known) in (int,float) and known>=0
                              and isinstance(proof,dict)
                              and str(proof.get('url','')).startswith('https://')
                              and proof.get('unit')=='TWD'
                              and proof.get('period_end')==f'{year}-12-31'
                              and bool(proof.get('basis')))
                    if verified:continue
                    if now<state.get('next_attempt',0):continue
                    if symbol.split('.')[0] in {s.split('.')[0] for s in candidates}:continue
                    candidates.append(symbol);chosen+=1
                    if chosen>=cap or len(candidates)>=batch_size:break
                put(cursor_key,{'value':(cursor+checked)%len(pool)})
            candidates=list(dict.fromkeys(candidates))[:batch_size]
            if not candidates:
                put('cashflow:year_cursor',{'value':(slot+1)%len(requested_years)});continue
            # Checkpoint first; a worker interruption cannot restart a whole market.
            form=fields(candidates,year,metric['metric'])
            try:
                html=download('/compare/report',form=form)
                values,issues=parse(html,candidates,year,today,metric['metric'])
                for symbol in candidates:
                    key=f'cashflow:state:{symbol}:{year}'
                    if symbol not in values:
                        reason=issues.get(symbol,'本批未取得該公司股利支出')
                        missing+=1
                        missing_reasons[reason]=missing_reasons.get(reason,0)+1
                        put(key,{'status':'missing','reason':reason,
                            'last_attempt':now,'next_attempt':now+7*86400});continue
                    old=copy.deepcopy(get('cashflow:official:'+symbol,{'rows':{}}))
                    old.setdefault('rows',{})[str(year)]=values[symbol]
                    old['updated_at']=datetime.now(timezone.utc).isoformat();put('cashflow:official:'+symbol,old)
                    put(key,{'status':'ok','last_success':now,'next_attempt':now+30*86400});updated+=1
                put('cashflow:year_cursor',{'value':(slot+1)%len(requested_years)})
            except StopIteration:break
            except Exception as exc:
                detail=describe(exc,'年度現金股利支出')
                status=getattr(getattr(exc,'response',None),'status_code',None)
                from app.providers.bounded_http import ResourceLimitError
                oversized=isinstance(exc,ResourceLimitError)
                if (oversized or detail['error_code']=='timeout') and len(candidates)>1:
                    batch_size=max(1,len(candidates)//2);put('cashflow:batch_size',{'value':batch_size})
                for symbol in candidates:put(f'cashflow:state:{symbol}:{year}',{
                    'status':'failed','last_attempt':now,'next_attempt':now+(300 if oversized else 3600 if detail['error_code'] in ('timeout','connection','http_500','http_502','http_503','http_504') else 86400),**detail})
                failures+=len(candidates)
                put('cashflow:year_cursor',{'value':(slot+1)%len(requested_years)})
                if status in (401,403,429):
                    put('annual:source:mopsfin',{'next_attempt':now+86400,**detail});break
        result={**summary,'state':'partial' if failures or not complete else 'finished','cash_requests':count,
            'elapsed_request_budget_seconds':round(time.monotonic()-start,2),
            'updated_fields':updated,'failed_feeds':failures,'missing_fields':missing,
            'missing_reasons':missing_reasons,'updated_at':datetime.now(timezone.utc).isoformat()}
        put('jobs:cash_dividends',result);return result


def exit_code(result):
    # A completed Python process is not evidence of a successful download.
    return 1 if result.get('state')=='failed' or (result.get('failed_feeds',0)>0 and not result.get('updated_fields',0)) else 0


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--symbols',default='');parser.add_argument('--years',type=int,default=5)
    parser.add_argument('--max-requests',type=int,default=2)
    args=parser.parse_args()
    selected=[s.strip() for s in args.symbols.split(',') if s.strip()] if args.symbols.strip() else None
    import json,sys
    result=run(selected,max_requests=args.max_requests,years=args.years)
    print(json.dumps(result,ensure_ascii=False))
    sys.exit(exit_code(result))
