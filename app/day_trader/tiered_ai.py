"""Two-stage research: quantitative ranking for all; AI only for unique top-N symbols."""
from app.day_trader.ranking import rank_four_modes, WEIGHTS

def build_tiered_plan(rows, *, top_n=10, ai_limit=40):
    if type(ai_limit) is not int or not 1<=ai_limit<=400:
        raise ValueError("ai_limit must be 1..400")
    ranked=rank_four_modes(rows,top_n=top_n)
    selected=[]
    seen=set()
    # Interleave ranks to avoid letting one category consume the whole budget.
    for index in range(top_n):
        for mode in WEIGHTS:
            entries=ranked["rankings"][mode]
            if index>=len(entries):continue
            symbol=entries[index]["symbol"]
            if symbol not in seen:
                seen.add(symbol)
                selected.append(symbol)
                if len(selected)>=ai_limit:break
        if len(selected)>=ai_limit:break
    return {"rankings":ranked["rankings"],"labels":ranked["labels"],
            "ai_symbols":selected,"ai_count":len(selected),
            "ai_limit":ai_limit,"quantitative_universe_size":len(rows),
            "ai_execution_status":"NOT_STARTED",
            "execution_enabled":False,
            "note":"只建立AI候選名單；尚未執行模型呼叫或排程推播。"}

def quantitative_lookup(rows, symbol):
    """Look up verified input scores without triggering AI."""
    for row in rows:
        if row.get("symbol")==symbol:
            return {"symbol":symbol,"fundamental_score":row.get("fundamental_score") if row.get("fundamental_complete") is True else None,
                    "technical_score":row.get("technical_score") if row.get("technical_complete") is True else None,
                    "data_stale":row.get("data_stale",False),
                    "ai_status":"NOT_REQUESTED"}
    return None
