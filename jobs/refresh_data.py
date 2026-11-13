"""Independent replenishment: no market scan and no LINE delivery."""
from datetime import datetime,timezone
from app.db import init_db,put,leased


def run():
    init_db()
    with leased('data:scheduled',300) as owned:
        if not owned:return {'state':'busy'}
        from jobs.maintenance import run as clean
        from jobs.refresh_fundamentals import run as fundamentals
        from jobs.refresh_eps import run as eps
        from jobs.refresh_annual import run as annual
        from jobs.refresh_us_prices import run as prices
        from jobs.v26_market_coverage import run as coverage_diagnostic
        from jobs.refresh_paid_dividends import run as paid
        from jobs.refresh_tw_financials import run as tw_financials
        from jobs.refresh_history import run as history
        from jobs.refresh_tw_prices import run as tw_prices
        from jobs.refresh_universe import build as universe
        from jobs.refresh_cash_dividends import run as cash
        # Each job reserves its own provider limits; a failure must not suppress others.
        result={'started_at':datetime.now(timezone.utc).isoformat(),'steps':{}}
        for name,step in [('maintenance',clean),('universe',universe),('tw_prices',tw_prices),('history',history),('fundamentals',fundamentals),('cash_dividends',cash),('tw_financials',tw_financials),('eps_first',eps),('eps_second',eps),('coverage_diagnostic',coverage_diagnostic),('annual',annual),('us_prices',prices),('paid',paid)]:
            try:
                value=step();state='finished'
                if isinstance(value,dict) and (value.get('state') in ('failed','partial','busy','limited','cooldown') or value.get('failed_feeds',0)):
                    state='partial'
                result['steps'][name]={'state':state,'result':value}
            except Exception:result['steps'][name]={'state':'failed','reason':'此批更新未完成，保留舊資料，待下次重試'}
        result['updated_at']=datetime.now(timezone.utc).isoformat()
        result['state']='partial' if any(s['state']!='finished' for s in result['steps'].values()) else 'finished'
        put('jobs:data_refresh',result)
        return result


if __name__=='__main__':print(run())
