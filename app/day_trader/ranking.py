"""Four independent research rankings; never places trades.

Input must contain independently validated fundamental/technical scores and
their data coverage. Missing scores are excluded rather than silently filled.
"""
from math import isfinite

WEIGHTS={
    "combined":(0.50,0.50),
    "long_term":(0.85,0.15),
    "swing":(0.40,0.60),
    "intraday":(0.10,0.90),
}
LABELS={"combined":"綜合","long_term":"長期","swing":"波段","intraday":"當沖"}

def _score(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not isfinite(value) or not 0<=value<=100:
        return None
    return float(value)

def rank_four_modes(rows, *, top_n=10):
    if type(top_n) is not int or not 1<=top_n<=100:raise ValueError("top_n must be 1..100")
    result={name:[] for name in WEIGHTS}
    seen=set()
    for row in rows:
        symbol=row.get("symbol")
        if not isinstance(symbol,str) or not symbol or symbol in seen:
            raise ValueError("missing or duplicate symbol")
        seen.add(symbol)
        f=_score(row.get("fundamental_score"))
        t=_score(row.get("technical_score"))
        fundamental_ok=row.get("fundamental_complete") is True and f is not None
        technical_ok=row.get("technical_complete") is True and t is not None
        if row.get("data_stale") is True:continue
        for mode,(wf,wt) in WEIGHTS.items():
            # Intraday and swing require fresh, complete intraday technical data.
            # Long-term requires complete fundamentals; combined requires both.
            eligible=(fundamental_ok and technical_ok) if mode=="combined" else (
                fundamental_ok if mode=="long_term" else technical_ok)
            if not eligible:continue
            if mode=="long_term":
                score=f if not technical_ok else wf*f+wt*t
            elif mode in ("swing","intraday"):
                score=t if not fundamental_ok else wf*f+wt*t
            else:
                score=wf*f+wt*t
            result[mode].append({"symbol":symbol,"name":row.get("name",symbol),
                "score":round(score,2),"fundamental_score":f if fundamental_ok else None,
                "technical_score":t if technical_ok else None,
                "signal":row.get("signal","NO_SIGNAL"),
                "research_only":True,"tradable":False})
    for mode in result:
        result[mode].sort(key=lambda x:(-x["score"],x["symbol"]))
        result[mode]=result[mode][:top_n]
    return {"rankings":result,"labels":LABELS,"top_n":top_n,
            "research_only":True,"execution_enabled":False,
            "note":"研究用排名；當沖／波段須另外核驗分鐘K棒時效與完整性，並非投資建議。"}
