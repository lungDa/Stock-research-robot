"""小批次可續跑掃描；逐檔checkpoint，報告只讀本次批次。"""
import argparse
import logging
import time
from datetime import datetime, timezone
from app.db import init_db, get, put, put_many
from app.providers.universe import load
from app.services.research import research
from app.services.watchlist import watches
from app.config import settings
from app.services.accounts import member_users
from app.services.freshness import local_now
from app.services.trading_calendar import calendar_snapshot, cached_read, expected_close
from app.providers.taiwan_official import history_months
log=logging.getLogger(__name__)


@calendar_snapshot
def run(limit=30, seconds=120):
    started=time.monotonic()
    init_db()
    # 即使手動給巨大參數，也限制為最多30檔/120秒（另保留收尾時間）。
    limit=max(1,min(int(limit),30)); seconds=max(1,min(int(seconds),120))
    universe=[s for s in load() if s.endswith(('.TW','.TWO'))]
    if not universe: raise RuntimeError('沒有可用台股母體')
    scope = get('universe:scope', {})
    if type(scope.get('count')) is int and scope['count'] != len(universe):
        put('scan:last_failure', {'state':'universe_mismatch','expected':scope['count'],
                                  'actual':len(universe),'updated_at':datetime.now(timezone.utc).isoformat()})
        raise RuntimeError('掃描清單與已保存母體筆數不符；先執行 refresh_universe')
    cursor=get('scan:cursor',{'cursor':0})['cursor']%len(universe)
    tracked=list(dict.fromkeys(s for u in member_users() for s in watches(u) if s.endswith(('.TW','.TWO'))))
    tcursor=get('scan:tracked_cursor',{'cursor':0})['cursor']%max(1,len(tracked))
    # 追蹤最多佔一半批次，避免親友清單太長造成市場輪掃停滯。
    selected=[tracked[(tcursor+i)%len(tracked)] for i in range(min(len(tracked),limit//2))]
    market_count=max(1,limit-len(selected))
    batch=[universe[(cursor+i)%len(universe)] for i in range(min(market_count,len(universe)))]
    symbols=list(dict.fromkeys(selected+batch))[:limit]
    expected = expected_close(local_now(), cached_read)
    phase = {'prepare': time.monotonic()-started, 'research': 0.0, 'rating': 0.0, 'checkpoint': 0.0}
    current_cursor, current_tracked_cursor = cursor, tcursor
    report={'updated_at':datetime.now(timezone.utc).isoformat(),'universe_size':len(universe),
            'target_date':local_now().date().isoformat(),'today_count':0,'data_dates':[],
            'expected_close_date':str(expected) if expected else None, 'expected_close_count':0,
            'candidates':[],'attempted':0,'failed':[],'income':[],'swing':[],'fresh_count':0,'cursor':cursor,
            'scope':'本次台股小批次結果；最多30檔，不代表全市場；美股暫不主動下載',
            'universe_partial':scope.get('partial',True) or scope.get('count') != len(universe),'budget_seconds':seconds}
    if report['universe_partial']: report['scope']+='；來源母體可能僅部分涵蓋'
    processed=set()
    for symbol in symbols:
        # 留15秒整理報告；來源不補歷史，僅共用官方快照及既有快取。
        if time.monotonic()-started >= max(0,seconds-15): break
        tick=time.monotonic()
        token=history_months.set(0)
        success=False
        try:
            fetched=research(symbol,refresh=False)
            success=True
        except Exception as exc:
            report['failed'].append(symbol)
            log.warning('略過 %s：%s',symbol,type(exc).__name__)
        finally:
            history_months.reset(token)
            phase['research']+=time.monotonic()-tick
        processed.add(symbol); report['attempted']+=1
        d=(fetched if isinstance(fetched,dict) else get('quote:'+symbol)) if success else None
        tick=time.monotonic()
        from app.services.freshness import market_usable
        if d and market_usable(d):
            from app.services.multifactor import rated
            d=rated(d,'public')
            report['fresh_count']+=1
            fields=('symbol','name','kind','date','currency','price','adjusted_close','ma20','ma60','yield','yield_basis','expense_ratio','expense_ratio_basis','volatility','volume_ratio','eps','roe','pe','income','swing','price_basis','source','updated_at','warnings','data_status','cached_at','history','technical_basis','adjustment_status','adjustment_reason','adjustment_anchor')
            report['candidates'].append({k:d.get(k) for k in fields})
            if d.get('date') == report['target_date']: report['today_count']+=1
            if expected and d.get('date') == str(expected): report['expected_close_count']+=1
            if d.get('date') and d['date'] not in report['data_dates']: report['data_dates'].append(d['date'])
            for mode in ('income','swing'):
                if (d['rating']['grade'] in ('買','強力買') if mode=='income' else d.get(mode,{}).get('matched')):
                    report[mode].append(f"{d['symbol']} {d['name']}｜{d['date']}")
        phase['rating']+=time.monotonic()-tick
        tick=time.monotonic()
        # 每檔checkpoint；工作中斷不會遺失整批輪掃位置。
        advanced=0
        for code in batch:
            if code not in processed: break
            advanced+=1
        report['cursor']=(cursor+advanced)%len(universe)
        checkpoints={}
        if report['cursor'] != current_cursor:
            current_cursor=report['cursor']
            checkpoints['scan:cursor']={'cursor':current_cursor}
        if tracked:
            done=sum(s in processed for s in selected)
            next_tracked=(tcursor+done)%len(tracked)
            if next_tracked != current_tracked_cursor:
                current_tracked_cursor=next_tracked
                checkpoints['scan:tracked_cursor']={'cursor':current_tracked_cursor}
        if checkpoints:
            put_many(checkpoints)
        phase['checkpoint']+=time.monotonic()-tick
    report['updated_at']=datetime.now(timezone.utc).isoformat()
    report['elapsed_seconds']=round(time.monotonic()-started,2)
    report['phase_seconds']={key:round(value,3) for key,value in phase.items()}
    if not report['fresh_count']:
        # 不能把失敗執行冒稱新報告，或讓通知推播空報告。
        put('scan:last_failure',report)
        raise RuntimeError('本次沒有成功取得行情，保留舊報告並停止本次通知')
    put('scan:latest',report)
    print({k:v for k,v in report.items() if k not in ('income','swing','candidates')})

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=30);p.add_argument('--seconds',type=int,default=120)
    a=p.parse_args()
    if a.limit<1 or a.seconds<1:p.error('參數必須為正數')
    run(a.limit,a.seconds)

