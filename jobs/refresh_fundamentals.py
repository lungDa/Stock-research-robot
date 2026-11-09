"""最多兩次1MiB串流下載、30秒軟預算；失敗保留資料並繼續輪替。"""
import logging
import time
from app.db import init_db,get,put
from app.providers.bounded_http import fetch_json
from app.providers.fundamentals import FEEDS,merge


def run():
    from app.db import leased
    from datetime import datetime,timezone
    init_db()
    with leased('annual:worker',180) as owned:
        if not owned:return []
        result=_run()
        put('jobs:fundamentals',{'updated_at':datetime.now(timezone.utc).isoformat(),'feeds':result})
        return result


def _run():
    init_db(); start=time.monotonic(); now=time.time()
    cursor=get('fundamentals:cursor',{'value':0})['value']%len(FEEDS)
    results=[]
    for offset in range(2):
        if time.monotonic()-start >= 20: break
        i=(cursor+offset)%len(FEEDS); market,category,url=FEEDS[i]
        key='fundamentals:feed:'+url
        state=get(key,{})
        status='cached'
        if now>=state.get('next_attempt',0):
            # 先寫冷卻，途中中斷也不連續重打；一天最多一次同端點。
            put(key,{'next_attempt':now+86400})
            try:
                payload=fetch_json(url,max_bytes=1048576,seconds=6,array=True)
                count=merge(market,payload['records'],category,url,now)
                if not count: raise ValueError('沒有可解析的基本面資料')
                status=f"{count}筆；完整={payload['complete']}"
                put(key,{'next_attempt':now+86400,'updated_at':now,
                         'complete':payload['complete'],'count':count})
            except Exception as exc:
                status='failed:'+type(exc).__name__
                logging.warning('基本面來源暫不可用，保留既有資料：%s %s',market,category)
        results.append({'market':market,'category':category,'status':status})
        put('fundamentals:cursor',{'value':(i+1)%len(FEEDS)})
    print(results)
    return results

if __name__=='__main__': run()
