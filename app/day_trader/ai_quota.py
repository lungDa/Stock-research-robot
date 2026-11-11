"""Daily per-stock AI research quota: 40 analyses/day, prioritised by rank and changes.

This is a planning layer, not yet a persistent atomic reservation or billing limit.
"""
from datetime import date

DAILY_LIMIT=40

def prioritise(candidates, *, limit=DAILY_LIMIT):
    if type(limit) is not int or limit<1:
        raise ValueError("limit must be a positive integer")
    seen=set()
    clean=[]
    for candidate in candidates:
        symbol=candidate.get("symbol")
        if not isinstance(symbol,str) or not symbol or symbol in seen:
            continue
        seen.add(symbol)
        rank=candidate.get("best_rank",999)
        change=candidate.get("score_change",0)
        if not isinstance(rank,int) or isinstance(rank,bool) or rank<1:
            rank=999
        if not isinstance(change,(int,float)) or isinstance(change,bool):
            change=0
        clean.append((candidate,rank,abs(change)))
    clean.sort(key=lambda item:(not bool(item[0].get("new_top_ten",False)),
                                item[1],-item[2],item[0]["symbol"]))
    chosen=[item[0]["symbol"] for item in clean[:limit]]
    deferred=[item[0]["symbol"] for item in clean[limit:]]
    return {"daily_limit":limit,"selected":chosen,"deferred":deferred,
            "selected_count":len(chosen),"deferred_count":len(deferred),
            "execution_status":"NOT_STARTED",
            "note":"同股當日分析次數須由持久化額度管理；備援模型可能增加API請求數。"}
