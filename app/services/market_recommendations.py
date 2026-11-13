"""全市場個人規則排名；共用快取，不改寫個人門檻。"""
import copy,math,time
from datetime import date,timedelta
from app.db import get,put,get_many
from app.services.multifactor import annual_rows,evaluate,settings_for,METRICS,config_hash
from app.services.freshness import local_now

def preferences(user):return get('recommendations:preferences:'+user,{'enabled':False})
def enable(user,enabled):
    if type(enabled) is not bool:raise ValueError('enabled須為布林值')
    put('recommendations:preferences:'+user,{'enabled':enabled});return preferences(user)

def calendar(year):
    from app.providers.bounded_http import fetch_json
    from app.providers.taiwan_official import trading_date
    key='recommendations:calendar:'+str(year);old=get(key,{})
    if old and time.time()-old.get('at',0)<6*3600:return old
    if year!=local_now().year:
        if old:return old
        raise RuntimeError('缺少該年度交易日曆，停止推播')
    rows=fetch_json('https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule',max_bytes=65536,seconds=6)
    if not isinstance(rows,list) or not rows:raise ValueError('交易日曆不可用')
    closed=[];opened=[]
    for row in rows:
        day=trading_date(row.get('Date',''))
        if date.fromisoformat(day).year!=year:raise ValueError('交易日曆年度不符')
        text=str(row.get('Name',''))+' '+str(row.get('Description',''))
        if ('開始交易' in text or '最後交易' in text) and '無交易' not in text:opened.append(day)
        else:closed.append(day)
    if len(closed)<5:raise ValueError('交易日曆不完整')
    result={'at':time.time(),'year':year,'closed':closed,'opened':opened}
    put(key,result);return result

def is_session(day):
    overrides=get('recommendations:session_overrides',{})
    if day.isoformat() in overrides:return bool(overrides[day.isoformat()])
    c=calendar(day.year)
    return day.isoformat() in c['opened'] or (day.weekday()<5 and day.isoformat() not in c['closed'])

def target_day(today,slot):
    if slot=='evening':return today
    day=today-timedelta(days=1)
    for _ in range(20):
        if is_session(day):return day
        day-=timedelta(days=1)
    raise RuntimeError('無法確認前一交易日')

def relaxed(config,round_):
    c=copy.deepcopy(config);factor=.9**round_
    for r in c['stock_rules']:
        if not r['enabled'] or r['metric'] in ('fcf_positive','fcf_coverage') or r['op']=='==':continue
        v=r['threshold']
        if r['op'] in ('>','>='):v=v*factor if v>=0 else v/factor
        else:v=v/factor if v>=0 else v*factor
        if r['metric']=='dividend_streak':v=math.ceil(v)
        r['threshold']=round(v,6)
    return c

def rank(items,config,today):
    """Fill up to ten slots by relaxation tier, preserving strict-first priority."""
    chosen = {}
    eligible = 0
    last_round = 0
    last_rules = config['stock_rules']
    for round_ in range(4):
        c = relaxed(config, round_)
        last_rules = c['stock_rules']
        last_round = round_
        for data, rows in items:
            symbol = data['symbol']
            if symbol in chosen or data.get('kind') != 'STOCK':
                continue
            r = evaluate(data, c, rows, today=today)
            required = [x for x in r['checks'] if x['required']]
            if round_ == 0 and required and all(x['passed'] is not None for x in required):
                eligible += 1
            if r['grade'] not in ('買', '強力買'):
                continue
            if any(x['passed'] is not True for x in required):
                continue
            chosen[symbol] = {**data, 'rating': r, 'relaxation_round': round_}
        if len(chosen) >= 10:
            break
    ranked = sorted(chosen.values(), key=lambda d: (
        d['relaxation_round'], -d['rating']['score'],
        -d['rating']['coverage'], d['symbol']))
    return {'items': ranked[:10], 'matched': len(chosen), 'round': last_round,
            'eligible': eligible, 'rules': last_rules,
            'original_config_hash': config_hash(config)}

def collect(symbols,snapshots,target,user,deadline):
    from app.providers.taiwan_official import build_result
    items=[];stats={'universe':len(symbols),'stock_quotes':0,'unknown_or_etf':0,'missing_price':0}
    base={k:get(k,{}) for k in ('fundamentals:index:TW','fundamentals:index:TWO')}
    for offset in range(0,len(symbols),10):
        if time.monotonic()>deadline:raise TimeoutError('全市場排名超過時間預算；不發送不完整批次')
        batch=symbols[offset:offset+10];keys=[]
        for s in batch:keys+=['quote:'+s,'twdaily:quote:'+s,'annual:shared:'+s,'annual:'+user+':'+s,'eps:official:'+s,'financial:official:'+s,'cashflow:official:'+s]
        docs={**base,**get_many(keys)}
        for s in batch:
            code,market=s.rsplit('.',1);meta=base['fundamentals:index:'+market].get(code,{})
            kind=meta.get('fields',{}).get('kind',{}).get('value');cached=docs.get('quote:'+s,{})
            if kind is None:kind=cached.get('kind')
            if kind in (None,'UNKNOWN') and (docs.get('eps:official:'+s,{}).get('rows') or docs.get('financial:official:'+s,{}).get('rows')):kind='STOCK'
            if kind!='STOCK':stats['unknown_or_etf']+=1;continue
            current=snapshots.get(market,{}).get(code)
            if not current or current.get('date')!=str(target):stats['missing_price']+=1;continue
            d={'symbol':s,'name':meta.get('name') or current['name'],'kind':'STOCK','currency':'TWD','price':current['close'],'adjusted_close':current['close'],'date':str(target),'ma20':None,'ma60':None,'data_status':'partial','price_basis':'未還原收盤價'}
            for old in [cached,docs.get('twdaily:quote:'+s,{})]:
                history=[{**r,'volume':r.get('volume')} for r in old.get('history',[]) if r.get('date','')<=str(target)]
                if history:
                    last=max(history,key=lambda r:r['date'])
                    if last['date']==str(target) and last['close']==current['close']:
                        rebuilt=build_result(s,history,d,[]);d.update({k:rebuilt[k] for k in ('ma20','ma60')});break
                if old.get('date')==str(target) and old.get('price')==current['close'] and old.get('data_status')!='stale':
                    d.update({k:old.get(k) for k in ('ma20','ma60')});break
            stats['stock_quotes']+=1;items.append((d,annual_rows(user,s,docs)))
    return items,stats

def messages(report):
    stats=report['coverage'];round_=report['round'];items=report['items']
    summary=(f"股海燈塔｜個人規則排名 {report['slot_label']}\n行情日 {report['target_date']}（收盤，非即時）\n母體 {stats['universe']}檔｜個股行情 {stats['stock_quotes']}檔\n必要資料足夠 {report['eligible']}檔｜符合 {report['matched']}檔｜列出 {len(items)}檔\n"+('母體來源部分涵蓋；' if report['universe_partial'] else '')+'資料缺漏者不算符合；排名限目前可評估範圍。\n'+(f'原條件無符合，採第{round_}輪放寬（每輪約10%）。\n' if round_ else '採原始個人規則。\n'))
    if not items:summary+='目前無可推薦個股，不以缺資料或未達標股票湊數。\n'
    summary+='本次門檻（期間不變）：\n'+'\n'.join(f"{METRICS[r['metric']]} {r['op']} {r['threshold']:g}（{r['years']}年，{'必要' if r['required'] else '加分'}）" for r in report['rules'] if r['enabled'])
    summary+='\n同分依資料完整度、股票代號排序。規則篩選非報酬預測。'
    result=[summary]
    for i,d in enumerate(items,1):
        r=d['rating'];missing=[x['label'] for x in r['checks'] if x['passed'] is None]
        result.append(f"第{i}名｜{d['name']}（{d['symbol']}）\n{r['grade']}｜分數 {r['score']}｜完整度 {r['coverage']}%\n收盤日 {d['date']}｜TWD {d['price']:.2f}\n"+(f'採第{round_}輪放寬條件。\n' if round_ else '符合原始規則。\n')+('加分項缺漏：'+'、'.join(missing)+'\n' if missing else '')+'依個人多因子規則篩選，非報酬保證。')
    if any(len(m)>4900 for m in result):raise ValueError('排名訊息過長，停止發送')
    return result
