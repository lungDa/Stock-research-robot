"""可續跑、分批掃描。每檔失敗隔離；排程直接執行，不依賴 Render 醒著。"""
import argparse,logging,time
from datetime import datetime,timezone
from app.db import init_db,get,put
from app.providers.universe import load
from app.services.research import research
from app.services.watchlist import watches
from app.config import settings
from app.providers.taiwan_official import history_months
log=logging.getLogger(__name__)
def run(limit=200,seconds=900):
    init_db(); started=time.monotonic()
    universe=load()
    if not universe: raise RuntimeError('母體為空')
    state=get('scan:cursor',{'cursor':0})
    cursor=state['cursor']%len(universe)
    size=min(limit,len(universe))
    batch=[universe[(cursor+i)%len(universe)] for i in range(size)]
    tracked=list(dict.fromkeys(s for u in settings.users.values() for s in watches(u)))
    symbols=list(dict.fromkeys(tracked+batch))
    failures=[]; processed=[]
    for symbol in symbols:
        if time.monotonic()-started>seconds: break
        token=history_months.set(4 if symbol in tracked else 0)
        try: research(symbol,refresh=True)
        except Exception:
            log.exception('scan item failed: %s',symbol);failures.append(symbol)
        finally:
            history_months.reset(token)
        processed.append(symbol)
    # 只前進到實際嘗試過的批次位置，不跳過時間預算外的項目。
    attempted=set(processed)
    advanced=0
    for symbol in batch:
        if symbol not in attempted: break
        advanced+=1
    put('scan:cursor',{'cursor':(cursor+advanced)%len(universe)})
    report={'updated_at':datetime.now(timezone.utc).isoformat(),'universe_size':len(universe),
            'attempted':len(processed),'failed':failures,'cursor':(cursor+advanced)%len(universe),
            'income':[],'swing':[],'fresh_count':0,'scope':'最近36小時已成功更新的母體；不是本次完整全市場掃描'}
    for symbol in universe:
        d=get('quote:'+symbol)
        if not d or time.time()-d['cached_at']>36*3600: continue
        report['fresh_count']+=1
        for mode in ('income','swing'):
            if d[mode]['matched']: report[mode].append(f"{d['symbol']} {d['name']}｜{d['date']}")
    put('scan:latest',report)
    print({k:v for k,v in report.items() if k not in ('income','swing')})
    if not processed or len(failures)==len(processed): raise RuntimeError('本次沒有成功取得行情')
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=200);p.add_argument('--seconds',type=int,default=900)
    args=p.parse_args()
    if args.limit<1 or args.seconds<1: p.error('limit/seconds 必須為正數')
    run(args.limit,args.seconds)
