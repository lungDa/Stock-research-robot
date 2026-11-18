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


def _component(checks):
    """Use only complete, explicitly evaluated conditions; no missing-as-zero."""
    if not checks or any(type(c.get('passed')) is not bool for c in checks):
        return None
    from math import isfinite
    weights=[c.get('weight') for c in checks]
    if any(type(w) not in (int,float) or not isfinite(w) or w<=0 for w in weights):
        return None
    return 100*sum(c['weight'] for c in checks if c['passed'])/sum(weights)


def refresh_cached(user, target_date=None):
    """Bounded personal watchlist report. Reads DB caches, never calls providers."""
    from app.services.watchlist import watches
    from app.services.research import quotes_for
    from app.services.multifactor import rated_many, ANNUAL
    from app.services.freshness import local_now, market_usable
    symbols=[s for s in watches(user) if s.endswith(('.TW','.TWO'))][:30]
    quotes=rated_many(quotes_for(symbols),user)
    rows=[]
    skipped={'missing_quote':len(symbols)-len(quotes),'stale_quote':0,
             'missing_fundamentals':0,'missing_daily_conditions':0}
    dates=[]
    for quote in quotes:
        if not market_usable(quote) or (target_date and quote.get('date')!=target_date):
            skipped['stale_quote']+=1
            continue
        checks=(quote.get('rating') or {}).get('checks') or []
        fundamental=_component([c for c in checks if c.get('metric') in ANNUAL|{'etf_yield','expense_pct'}])
        technical=_component([c for c in checks if c.get('metric') in {'price_ma20','ma20_ma60','volatility'}])
        skipped['missing_fundamentals']+=int(fundamental is None)
        skipped['missing_daily_conditions']+=int(technical is None)
        rows.append({'symbol':quote['symbol'],'name':quote.get('name',quote['symbol']),
                     'fundamental_score':fundamental,'technical_score':technical,
                     'fundamental_complete':fundamental is not None,'technical_complete':technical is not None,
                     'intraday_verified':False,'signal':(quote.get('rating') or {}).get('grade','資料不足')})
        dates.append(quote['date'])
    report=rank_four_modes(rows)
    report.update(as_of=target_date or (min(dates) if dates else None),
                  generated_at=local_now().isoformat(),scope='personal_watchlist',
                  scope_label='個人追蹤清單（最多30檔台股）；非全市場排名',
                  symbols_checked=len(symbols),skipped=skipped,
                  score_basis='依個人已啟用條件的權重計算通過率；未通過條件仍可列入研究排序，並非買入建議。',
                  mode_messages={'combined':'需要完整基本面與日線條件。',
                                 'long_term':'需要完整基本面條件。',
                                 'swing':'尚未接入並驗證分鐘行情，暫不產生波段排名。',
                                 'intraday':'尚未接入並驗證分鐘行情，暫不產生當沖排名。'})
    put('four_rankings:latest:'+user,report)
    return report

def summary(report):
    if not report or not report.get("as_of"):return None
    lines=["股海燈塔｜四模式研究排名", "資料時間："+str(report["as_of"])]
    if report.get('scope_label'):lines.append(report['scope_label'])
    for mode,label in LABELS.items():
        rows=report.get("rankings",{}).get(mode,[])
        lines.append(label+"前10："+("、".join(str(i+1)+"."+r["symbol"] for i,r in enumerate(rows[:10])) if rows else "資料不足，暫不排名"))
    lines.append("研究用途；非即時報價、非下單建議。")
    text="\n".join(lines)
    if len(text)>4900:raise ValueError("LINE message too long")
    return text
