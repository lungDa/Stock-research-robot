"""Metered execution boundary for actual Gemini/OpenAI commentary.

Only a successful provider response completes the daily charge. A repeated
request returns the saved result without invoking the model again.
"""
from app.db import get, put
from app.day_trader.ai_usage import reserve, finish, today
from app.day_trader.dual_ai import review

def metered_review(user, report, *, kind="normal", enabled=False,
                   primary="gemini", fallback="openai", caller=None):
    if not enabled:
        return {"status":"DISABLED","provider":None,"commentary":None,
                "scores_unchanged":True,"charged":False}
    if not isinstance(user,str) or not user:
        raise ValueError("authenticated user required")
    if not isinstance(report,dict) or not isinstance(report.get("symbol"),str):
        raise ValueError("symbol required")
    symbol=report["symbol"].strip().upper()
    if not symbol or len(symbol)>30:
        raise ValueError("invalid symbol")
    if kind not in ("normal","emergency"):
        raise ValueError("invalid quota kind")
    day=today()
    key=f"ai:result:{user}:{day}:{kind}:{symbol}"
    state=reserve(user,symbol,kind)
    if state=="cached":
        saved=get(key)
        if isinstance(saved,dict) and saved.get("status")=="OK":
            return {**saved,"charged":False,"reused":True}
        # Never call the provider again under a completed quota record.
        return {"status":"RESULT_UNAVAILABLE","charged":False,"reused":False}
    if state!="reserved":
        return {"status":"QUOTA_"+state.upper(),"charged":False,"reused":False}
    completed=False
    try:
        result=review({**report,"symbol":symbol},primary=primary,
                      fallback=fallback,enabled=True,caller=caller)
        if result.get("status")!="OK":
            return {**result,"charged":False,"reused":False}
        # Store before committing the charge; if storage fails release quota.
        put(key,result)
        completed=finish(user,symbol,kind,success=True,day=day)
        if not completed:
            return {"status":"QUOTA_COMMIT_FAILED","charged":False}
        return {**result,"charged":True,"reused":False}
    finally:
        if not completed:
            finish(user,symbol,kind,success=False,day=day)
