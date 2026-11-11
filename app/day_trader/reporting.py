"""Opt-in four-mode research reports; no invented ranking scores."""
from app.db import get, put
from app.day_trader.ranking import rank_four_modes, LABELS

def preferences(user):
    return get("four_rankings:preferences:"+user, {"enabled":False})

def set_enabled(user, enabled):
    if type(enabled) is not bool:raise ValueError("enabled must be boolean")
    state={"enabled":enabled}
    put("four_rankings:preferences:"+user,state)
    return state

def latest(user):
    return get("four_rankings:latest:"+user,{})

def build_report(user, rows, as_of):
    """Call only after verified fundamental and intraday technical feeds are available."""
    result=rank_four_modes(rows)
    result["as_of"]=as_of
    put("four_rankings:latest:"+user,result)
    return result

def summary(report):
    if not report or not report.get("as_of"):return None
    lines=["股海燈塔｜四模式研究排名", "資料時間："+str(report["as_of"])]
    for mode,label in LABELS.items():
        rows=report.get("rankings",{}).get(mode,[])
        lines.append(label+"前10："+("、".join(str(i+1)+"."+r["symbol"] for i,r in enumerate(rows[:10])) if rows else "資料不足，暫不排名"))
    lines.append("研究用途；非即時報價、非下單建議。")
    text="\n".join(lines)
    if len(text)>4900:raise ValueError("LINE message too long")
    return text
