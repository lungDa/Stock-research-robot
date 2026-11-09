"""可重現的個人多因子規則；所有百分比欄位均使用百分點。"""
import copy,hashlib,json,math
from datetime import date
from app.services.freshness import local_now

METRICS={'eps_latest':'最近完整年度EPS（報表幣別／股）','eps_avg':'多年平均年度EPS（報表幣別／股）',
 'yield_avg':'多年平均年度現金殖利率（%）','dividend_streak':'連續配發現金股利年數',
 'roe_avg':'多年平均年度ROE（%）','fcf_positive':'期間每年自由現金流為正',
 'fcf_coverage':'期間最低自由現金流／現金股利總額','revenue_cagr':'年度營收CAGR（%）',
 'price_ma20':'股價高於20日均線（%）','ma20_ma60':'20日高於60日均線（%）',
 'etf_yield':'ETF近一年已發配息率（%）','expense_pct':'ETF年度總費用率（%）','volatility':'年化波動（%）'}
ANNUAL={'eps_latest','eps_avg','yield_avg','dividend_streak','roe_avg','fcf_positive','fcf_coverage','revenue_cagr'}

def rule(metric,threshold,years=5,op='>',required=True,weight=10):
    return dict(metric=metric,threshold=threshold,years=years,op=op,required=required,weight=weight,enabled=True)

DEFAULT={'version':1,'missing_policy':'block','strong_score':85,'buy_score':65,'daily_cap':3,
 'notify_direction':'both','stock_rules':[rule('eps_latest',1,1),rule('eps_avg',2),
 rule('yield_avg',5),rule('dividend_streak',10,10, '>='),rule('roe_avg',15),
 rule('fcf_positive',1,5,'=='),rule('fcf_coverage',1,5,'>='),rule('revenue_cagr',5),
 rule('price_ma20',0,1,required=False),rule('ma20_ma60',0,1,required=False)],
 'etf_rules':[rule('etf_yield',3,1),rule('expense_pct',.5,1,'<'),
 rule('price_ma20',0,1,required=False),rule('ma20_ma60',0,1,required=False),
 rule('volatility',25,1,'<',required=False)]}

def validate(config):
    if not isinstance(config,dict):raise ValueError('設定須為物件')
    c=copy.deepcopy(config)
    if c.get('missing_policy') not in ('block','available'):raise ValueError('缺資料模式錯誤')
    if c.get('notify_direction') not in ('both','up'):raise ValueError('通知方向錯誤')
    for key in ('strong_score','buy_score'):
        if type(c.get(key)) not in (int,float) or not math.isfinite(c[key]):raise ValueError('分數必須為有限數值')
    if not 0<c['buy_score']<c['strong_score']<=100:raise ValueError('分級門檻須為0＜買＜強力買≤100')
    if type(c.get('daily_cap')) is not int or not 1<=c['daily_cap']<=10:raise ValueError('每日訊息上限為1至10')
    for key in ('stock_rules','etf_rules'):
        rules=c.get(key)
        if not isinstance(rules,list) or not 1<=len(rules)<=24:raise ValueError('每類須有1至24條規則')
        allowed=ANNUAL|{'price_ma20','ma20_ma60'} if key=='stock_rules' else set(METRICS)-ANNUAL
        for r in rules:
            if set(r)!= {'metric','threshold','years','op','required','weight','enabled'}:raise ValueError('規則欄位錯誤')
            if r['metric'] not in allowed or r['op'] not in ('>','>=','<','<=','=='):raise ValueError('不支援的因子或運算')
            if type(r['years']) is not int or not 1<=r['years']<=10:raise ValueError('期間為1至10年')
            for k in ('threshold','weight'):
                if type(r[k]) not in (int,float) or not math.isfinite(r[k]):raise ValueError('門檻與權重須為有限數值')
            if not 0<r['weight']<=100:raise ValueError('權重須大於0且不超過100')
            if type(r['enabled']) is not bool or type(r['required']) is not bool:raise ValueError('啟用與必要欄位須為布林值')
        if not any(r['enabled'] for r in rules):raise ValueError('每類至少啟用一條規則')
    return c

def settings_for(user):
    from app.db import get
    return get('strategy:'+user,copy.deepcopy(DEFAULT))
def save_settings(user,c):
    from app.db import put
    c=validate(c);put('strategy:'+user,c);return c

def config_hash(c):return hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()[:16]

def annual_rows(user,symbol,documents=None):
    from app.db import get
    read=get if documents is None else lambda k,d=None:documents.get(k,d)
    official={}
    if symbol.endswith(('.TW','.TWO')):
        code,market=symbol.rsplit('.',1)
        fields=read('fundamentals:index:'+market,{}).get(code,{}).get('fields',{})
        eps=fields.get('eps',{})
        if eps.get('period','').endswith('Q4'):
            official[eps['period'][:4]]={'eps':eps['value'],'source_url':eps['source'],'provenance':'official_Q4','as_of':eps.get('as_of','')}
    private=read('annual:'+user+':'+symbol,{})
    shared=read('annual:shared:'+symbol,{})
    rows=copy.deepcopy(shared.get('rows',{}))
    saved=read('eps:official:'+symbol,{}).get('rows',{})
    for snapshot in (saved,official):
        for year,row in snapshot.items():
            existing=rows.setdefault(year,{})
            old_source=existing.get('field_sources',{}).get('eps',{})
            if row.get('as_of','')<old_source.get('as_of',existing.get('as_of','')) and existing.get('eps') is not None:continue
            if not existing:existing.update(copy.deepcopy(row))
            existing['eps']=row['eps']
            existing.setdefault('field_sources',{})['eps']=copy.deepcopy(row.get('field_sources',{}).get('eps',{
                'url':row.get('source_url',''),'as_of':row.get('as_of',''),'provenance':row.get('provenance','official_Q4')}))
            if 'notes' in existing:existing['notes']=[n for n in existing['notes'] if 'EPS未直接' not in n]
    # Official annual EPS/ROE for both markets. Per-field sources remain separate.
    for year,row in read('financial:official:'+symbol,{}).get('rows',{}).items():
        current=rows.setdefault(year,{})
        for field in ('eps','roe_pct'):
            if field not in row:continue
            source=row.get('field_sources',{}).get(field,{})
            old=current.get('field_sources',{}).get(field,{})
            if current.get(field) is not None and source.get('as_of','')<old.get('as_of',''):continue
            if not current:current.update({k:v for k,v in row.items() if k not in ('eps','roe_pct','field_sources')})
            current[field]=row[field]
            current.setdefault('field_sources',{})[field]=copy.deepcopy(source)
            if field=='eps' and 'notes' in current:current['notes']=[n for n in current['notes'] if 'EPS未直接' not in n]
    for year,row in private.items():
        existing=rows.setdefault(year,{})
        sources={**existing.get('field_sources',{}),**row.get('field_sources',{})}
        for key in row:
            if key in ('eps','roe_pct','cash_yield_pct','cash_dividend_per_share','operating_cash_flow','capital_expenditure','cash_dividends_paid','revenue') and key not in row.get('field_sources',{}):
                sources[key]={'url':row.get('source_url',''),'as_of':row.get('as_of',''),'provenance':row.get('provenance','user_import')}
        existing.update(row)
        existing['field_sources']=sources
    return rows

def value_for(data,rows,metric,years,today):
    end=today.year-1
    if metric in ANNUAL:
        needed=1 if metric=='eps_latest' else years+1 if metric=='revenue_cagr' else years
        selected=[rows.get(str(end-i),{}) for i in range(needed)]
        def series(key):
            vals=[r.get(key) for r in selected]
            return vals if all(type(v) in (int,float) and math.isfinite(v) for v in vals) else None
        if metric=='dividend_streak':
            # A directly reported paid common-dividend total also proves a year
            # paid dividends. A declared dividend never qualifies as paid.
            vals=[r.get('cash_dividend_per_share',r.get('cash_dividends_paid')) for r in selected]
            if not all(type(v) in (int,float) and math.isfinite(v) for v in vals):vals=None
            return None if vals is None else sum(1 for _ in _positive_prefix(vals))
        key={'eps_latest':'eps','eps_avg':'eps','yield_avg':'cash_yield_pct','roe_avg':'roe_pct','revenue_cagr':'revenue'}.get(metric)
        if key:
            vals=series(key)
            if vals is None:return None
            if metric=='eps_latest':return vals[0]
            if metric=='revenue_cagr':
                return ((vals[0]/vals[-1])**(1/years)-1)*100 if vals[-1]>0 and vals[0]>=0 else None
            return sum(vals)/len(vals)
        ocf=series('operating_cash_flow');capex=series('capital_expenditure')
        if ocf is None or capex is None:return None
        fcf=[a-b for a,b in zip(ocf,capex)]
        if metric=='fcf_positive':return int(all(v>0 for v in fcf))
        div=series('cash_dividends_paid')
        if div is None:return None
        # 無股利且FCF為正視為足以覆蓋，避免除以0；FCF非正仍不符合。
        return min(a/b if b>0 else (1 if a>0 else 0) for a,b in zip(fcf,div))
    if data.get('data_status')=='stale':return None
    try:
        age=(today-date.fromisoformat(data['date'])).days
        if not 0<=age<=7:return None
    except (ValueError,KeyError,TypeError):return None
    if metric=='price_ma20':
        a,b=data.get('adjusted_close'),data.get('ma20')
        return (a/b-1)*100 if a is not None and b is not None and b>0 else None
    if metric=='ma20_ma60':
        a,b=data.get('ma20'),data.get('ma60')
        return (a/b-1)*100 if a is not None and b is not None and b>0 else None
    # ETF指標只接受明確聲明期間的資料；舊Yahoo/官方公告殖利率不可替代。
    key={'etf_yield':'yield','expense_pct':'expense_ratio','volatility':'volatility'}[metric]
    expected='trailing_paid_365d' if metric=='etf_yield' else 'annual_total_expense'
    if metric!='volatility' and data.get(key+'_basis')!=expected:return None
    v=data.get(key)
    return v*100 if metric=='expense_pct' and v is not None else v

def _positive_prefix(values):
    for v in values:
        if v<=0:break
        yield v

def evaluate(data,c,rows=None,today=None):
    today=today or local_now().date(); rows=rows or {}
    kind=data.get('kind')
    if kind not in ('STOCK','ETF'):return {'grade':'資料不足','score':None,'coverage':0,'checks':[],'reason':'商品分類不明'}
    checks=[]
    ops={'>':lambda a,b:a>b,'>=':lambda a,b:a>=b,'<':lambda a,b:a<b,'<=':lambda a,b:a<=b,'==':lambda a,b:a==b}
    for r in c['stock_rules' if kind=='STOCK' else 'etf_rules']:
        if not r['enabled']:continue
        v=value_for(data,rows,r['metric'],r['years'],today)
        if v is not None and (not isinstance(v,(int,float)) or not math.isfinite(v)):v=None
        checks.append({**r,'label':METRICS[r['metric']],'value':v,'passed':None if v is None else ops[r['op']](v,r['threshold'])})
    known=[r for r in checks if r['passed'] is not None]
    weight=sum(r['weight'] for r in checks);available=sum(r['weight'] for r in known)
    score=round(100*sum(r['weight'] for r in known if r['passed'])/available,2) if available else None
    missing=len(known)<len(checks)
    required_missing=any(r['required'] and r['passed'] is None for r in checks)
    from app.services.freshness import market_usable
    market_ok=market_usable(data,today)
    if not market_ok or required_missing or not known or (missing and c['missing_policy']=='block'):grade='資料不足'
    elif any(r['required'] and r['passed'] is False for r in checks):grade='觀望'
    elif score>=c['strong_score'] and not missing:grade='強力買'
    elif score>=c['buy_score']:grade='買'
    else:grade='觀望'
    reasons=[]
    if not market_ok:reasons.append('行情過舊或不完整，停止買入分級')
    if required_missing:reasons.append('必要條件缺資料')
    return {'grade':grade,'score':score,'coverage':round(100*available/weight,1) if weight else 0,
        'market_usable':market_ok,'required_missing':required_missing,
        'checks':checks,'config_hash':config_hash(c),'reason':'；'.join(reasons+['規則分級，非報酬預測；分數僅計已知資料，缺資料不補零'])}

def rated(data,user,config=None,documents=None):
    if documents is None:
        from app.db import get_many
        documents=get_many(_rating_keys([data],user))
        return rated(data,user,config or documents.get('strategy:'+user,copy.deepcopy(DEFAULT)),documents)
    from app.db import get
    read=get if documents is None else lambda k,d=None:documents.get(k,d)
    shared=(get('annual:shared:'+data['symbol'],{}) if documents is None else documents.get('annual:shared:'+data['symbol'],{}))
    data=copy.deepcopy(data)
    from app.services.freshness import mark_cached
    if 'cached_at' in data:data=mark_cached(data)
    if data['symbol'].endswith(('.TW','.TWO')):
        from app.providers.fundamentals import attach as official_attach
        data=official_attach(data,documents)
        if data.get('kind')=='UNKNOWN' and (read('eps:official:'+data['symbol'],{}).get('rows') or read('financial:official:'+data['symbol'],{}).get('rows')):
            data['kind']='STOCK'
            data['warnings']=[w for w in data.get('warnings',[]) if 'UNKNOWN' not in w]
        display=read('financial:official:'+data['symbol'],{}).get('company_display','')
        if display and data.get('name') in (None,data['symbol'],data['symbol'].split('.')[0]):data['name']=display.split(' ',1)[-1]
    rows=annual_rows(user,data['symbol'],documents)
    if data['symbol'].endswith(('.TW','.TWO')):
        # Rebuild from persisted raw periods after upgrades, without redownloading.
        from app.providers.trailing import taiwan_trailing
        from app.providers.annual_free import TW_DATASETS
        derived=taiwan_trailing(data['symbol'],{feed:read('annual:feed:'+data['symbol']+':'+feed,{}).get('records',[]) for feed in TW_DATASETS[:2]},local_now().date())
        if derived:
            shared=copy.deepcopy(shared)
            for key,value in derived.items():
                if value.get('period_end','')>=shared.get('trailing',{}).get(key,{}).get('period_end',''):
                    shared.setdefault('trailing',{})[key]=value
        from app.providers.trailing import reported_twelve_month_eps
        known_period=read('fundamentals:index:'+data['symbol'].rsplit('.',1)[1],{}).get(data['symbol'].split('.')[0],{}).get('fields',{}).get('eps',{}).get('period')
        reported=reported_twelve_month_eps(rows,shared.get('trailing',{}),known_period,local_now().date())
        if reported:
            shared=copy.deepcopy(shared)
            shared.setdefault('trailing',{}).setdefault('eps_ttm',reported)
    if data.get('kind') in ('STOCK','ETF'):
        from app.services.trailing_metrics import attach
        data=attach(data,shared,read('paid:shared:'+data['symbol'],{}),read('ttm:'+user+':'+data['symbol'],{}))
    from app.services.analysis import enrich
    data=enrich(data)
    rating=evaluate(data,config or settings_for(user),rows)
    from app.services.data_quality import report
    return {**data,'rating':rating,'data_quality':report(data,rows,rating,read),
            'annual_rows':rows,
            'annual_refresh':_annual_state(data['symbol'],documents),
            'annual_sources':[{'year':year,'source':r.get('source_url',''),'provenance':r.get('provenance','unknown'),
                'currency':r.get('currency',data.get('currency','未知')),'period_end':r.get('period_end',''),'field_sources':r.get('field_sources',{}),
                'notes':'；'.join(r.get('notes',[]))} for year,r in sorted(rows.items(),reverse=True)]}

def _annual_state(symbol,documents):
    from app.db import get
    read=get if documents is None else lambda k,d=None:documents.get(k,d)
    shared=read('annual:shared:'+symbol,{})
    return {k:shared[k] for k in ('updated_at','status','notes') if k in shared}

def _rating_keys(items,user):
    keys=['strategy:'+user]+['annual:'+user+':'+d['symbol'] for d in items]
    keys+=['annual:shared:'+d['symbol'] for d in items]
    keys+=['annual:feed:'+d['symbol']+':'+feed for d in items if d['symbol'].endswith(('.TW','.TWO')) for feed in ('TaiwanStockFinancialStatements','TaiwanStockBalanceSheet')]
    keys+=['paid:shared:'+d['symbol'] for d in items]+['ttm:'+user+':'+d['symbol'] for d in items]
    keys+=['eps:official:'+d['symbol'] for d in items]
    keys+=['financial:official:'+d['symbol'] for d in items]
    keys+=['annual:query_result:'+d['symbol'] for d in items]
    markets={d['symbol'].rsplit('.',1)[-1] for d in items if d['symbol'].endswith(('.TW','.TWO'))}
    keys+=['fundamentals:index:'+market for market in sorted(markets)]+['annual:source:finmind','annual:source:sec','annual:source:mopsfin']
    return list(dict.fromkeys(keys))


def rated_many(items,user):
    from app.db import get_many
    keys=_rating_keys(items,user)
    # 30 candidates + private/shared rows exceed the database's 80-key bound.
    documents={}
    for offset in range(0,len(keys),80):documents.update(get_many(keys[offset:offset+80]))
    c=documents.get('strategy:'+user,copy.deepcopy(DEFAULT))
    return [rated(d,user,c,documents) for d in items]


def rated_report(report,user):
    items=rated_many(report.get('candidates',[])[:30],user)
    return {**report,'ratings':items,
        'income':[f"{d['symbol']} {d['name']}｜{d['date']}" for d in items if d['rating']['grade'] in ('買','強力買')],
        'swing':[f"{d['symbol']} {d['name']}｜{d['date']}" for d in items if d.get('swing',{}).get('matched')]}
