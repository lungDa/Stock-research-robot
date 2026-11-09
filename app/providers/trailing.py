"""Period-aware trailing metrics. No network requests or annual/TTM substitution."""
from datetime import date,timedelta
from app.providers.annual_free import finite,valid_day,TW_DATASETS,tw_series


def point(value,start,end,source,basis):
    return {'value':value,'period_start':str(start),'period_end':str(end),'source':source,'basis':basis}


def ttm_amount(records):
    """Annual + current YTD - matching prior YTD; never sum overlapping facts."""
    if not records:return None
    end=max(r['end'] for r in records)
    same=[r for r in records if r['end']==end and r.get('start')]
    full=[r for r in same if 330<=(date.fromisoformat(end)-date.fromisoformat(r['start'])).days<=400]
    if full:return max(full,key=lambda r:r['filed'])
    ytd=sorted(same,key=lambda r:r['start'])
    for current in ytd:
        start=date.fromisoformat(current['start'])
        annuals=[r for r in records if r['end']==str(start-timedelta(days=1)) and r.get('start')
                 and 330<=(date.fromisoformat(r['end'])-date.fromisoformat(r['start'])).days<=400]
        if not annuals:continue
        annual=max(annuals,key=lambda r:r['filed'])
        prior=[r for r in records if r.get('start')==annual['start'] and
            330<=(date.fromisoformat(end)-date.fromisoformat(r['end'])).days<=400]
        if len(prior)!=1:continue
        previous=prior[0]
        return {'value':annual['value']+current['value']-previous['value'],
            'start':str(date.fromisoformat(previous['end'])+timedelta(days=1)),
            'end':end,'filed':max(r['filed'] for r in (annual,current,previous)),
            'derived':'annual_plus_current_ytd_minus_prior_ytd'}
    return None


def sec_period_records(payload,metric,unit,today):
    records={}
    for r in payload.get('units',{}).get(unit,[]):
        end=valid_day(r.get('end'));start=valid_day(r.get('start'));filed=valid_day(r.get('filed'));v=finite(r.get('val'))
        if r.get('form') not in ('10-K','10-K/A','10-Q','10-Q/A') or not end or end>today or not filed or filed>today or v is None:continue
        if metric!='equity' and (not start or not 45<=(end-start).days<=400):continue
        key=(str(start) if start else None,str(end))
        if key not in records or str(filed)>records[key]['filed']:
            records[key]={'value':v,'start':key[0],'end':key[1],'filed':str(filed)}
    return list(records.values())


def us_trailing(concepts,today):
    result={};source='SEC companyconcept / us-gaap'
    ni=ttm_amount(concepts.get('net_income',[]))
    if ni:
        end=date.fromisoformat(ni['end']);start=date.fromisoformat(ni['start'])
        if (today-end).days<=190:
            equity={r['end']:r['value'] for r in concepts.get('equity',[]) if not r.get('start')}
            a=equity.get(str(start-timedelta(days=1)));b=equity.get(str(end))
            if a is not None and b is not None and min(a,b)>0:
                result['roe_ttm_pct']=point(ni['value']/((a+b)/2)*100,start,end,source,'TTM net income / mean opening and closing equity')
            # A reported twelve-month EPS is valid only at the same latest end.
            eps=[r for r in concepts.get('eps',[]) if r.get('start')==ni['start'] and r['end']==ni['end']]
            if len(eps)==1:result['eps_ttm']=point(eps[0]['value'],start,end,source,'reported diluted EPS for matching twelve-month period')
    return result


def taiwan_trailing(symbol,feeds,today):
    code=symbol.split('.')[0];result={}
    income=tw_series(feeds.get(TW_DATASETS[0],[]),code)
    balance=tw_series(feeds.get(TW_DATASETS[1],[]),code)
    dates=sorted(d for d,tag in income if tag=='IncomeAfterTaxes' and income[(d,tag)] is not None and d<=str(today))
    if not dates:return result
    end=date.fromisoformat(dates[-1]);q=(end.month-1)//3
    expected=[];year=end.year
    for offset in range(4):
        n=year*4+q-offset;y,quarter=divmod(n,4)
        expected.append(f'{y}-{("03-31","06-30","09-30","12-31")[quarter]}')
    vals=[income.get((d,'IncomeAfterTaxes')) for d in expected]
    if any(v is None for v in vals) or (today-end).days>190:return result
    oldest=date.fromisoformat(expected[-1]);start=date(oldest.year,(oldest.month-1)//3*3+1,1)
    a=balance.get((str(start-timedelta(days=1)),'Equity'));b=balance.get((str(end),'Equity'))
    if a is not None and b is not None and min(a,b)>0:
        result['roe_ttm_pct']=point(sum(vals)/((a+b)/2)*100,start,end,'FinMind financial statements + balance sheet','TTM total net income / mean opening and closing total equity')
    # No sum of EPS values with unverified share bases.
    return result
