"""Administrator-only aggregate diagnostics; never return identities or secrets."""
import os,time
from app.db import get,documents_with_prefix,Session,ProviderBudget
from sqlalchemy import text
from app.services.data_queue import requested


def overview():
    with Session() as session:session.execute(text('SELECT 1'))
    now=time.time();queues=requested()
    from app.services.freshness import local_now
    with Session() as session:
        usage={source:(row.used if (row:=session.get(ProviderBudget,source+':'+str(local_now().date()))) else 0)
               for source in ('finmind','sec','twse_eps','mopsfin')}
    states=list(documents_with_prefix('annual:feed:',1000).values())
    from app.services.multifactor import rated_many
    from app.services.research import quotes_for
    symbols=[key[len('quote:'):] for key in documents_with_prefix('quote:',30)]
    items=rated_many(quotes_for(symbols),'public')
    metrics={}
    for item in items:
        for check in item['rating'].get('checks',[]):
            value=metrics.setdefault(check['metric'],{'label':check['label'],'known':0,'sampled':0})
            value['sampled']+=1;value['known']+=int(check['passed'] is not None)
    for value in metrics.values():value['coverage_pct']=round(value['known']/value['sampled']*100,1)
    return {'database':'ok','queue_symbols':len(queues),'queue_scope':'有效查詢需求，保留14天；不等同仍缺欄位數',
            'oldest_request_age_hours':round(max([now-r['requested_at'] for r in queues.values()] or [0])/3600,1),
            'feed_states_sampled':len(states),'feed_sample_limit':1000,
            'feed_ok':sum(r.get('status')=='ok' for r in states),
            'feed_failed':sum(r.get('status')=='failed' for r in states),
            'field_coverage_sample':list(metrics.values()),'field_coverage_symbols':len(items),
            'field_coverage_scope':'最多30檔既有行情，以公開預設規則抽樣；不是全市場完整率',
            'source_configured':{'finmind':bool(os.getenv('FINMIND_TOKEN','').strip()),
                                 'sec':bool(os.getenv('SEC_USER_AGENT','').strip())},
            'daily_provider_requests':{s:{'used':usage[s],'cap':cap} for s,cap in [('finmind',100),('sec',60),('twse_eps',12),('mopsfin',48)]},
            'source_retry_after_seconds':{s:max(0,round(get('annual:source:'+s,{}).get('next_attempt',0)-now)) for s in ('finmind','sec','mopsfin')},
            'jobs':{s:get('jobs:'+s,{}) for s in ('annual','fundamentals','tw_financials','cash_dividends','maintenance','data_refresh')},
            'scan':{k:v for k,v in get('scan:latest',{}).items() if k in ('updated_at','attempted','fresh_count','today_count','universe_size')},
            'scan_last_failure_at':get('scan:last_failure',{}).get('updated_at')}
