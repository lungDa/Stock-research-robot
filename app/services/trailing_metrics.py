"""Attach verifiable current-period metrics without changing annual rule definitions."""
import copy,time
from datetime import date,timedelta
from app.providers.annual_free import finite
from app.services.freshness import local_now


def attach(data,shared,paid=None,manual=None,today=None):
    data=copy.deepcopy(data);today=today or local_now().date()
    if data.get('kind') not in ('STOCK','ETF'):return data
    details=copy.deepcopy(shared.get('trailing',{}));manual=manual or {}
    details.pop('paid_yield_pct',None)  # Always recompute the rolling window at the current price.
    if manual:details['eps_ttm']=manual
    price=finite(data.get('price'));price_date=None
    try:price_date=date.fromisoformat(data.get('date',''))
    except ValueError:pass
    quote_ok=price and price>0 and price_date and 0<=(today-price_date).days<=7 and data.get('data_status') not in ('stale','fundamentals_only')
    profile=shared.get('fund_profile',{})
    if profile.get('payments'):
        from datetime import datetime,timezone
        try:stamp=datetime.fromisoformat(str(profile['as_of'])).replace(tzinfo=timezone.utc).timestamp()
        except (KeyError,ValueError):stamp=0
        paid={'payments':profile['payments'],'splits':profile.get('splits',[]),
              'currency':profile.get('currency'),'fetched_at':profile.get('fetched_at',stamp),'source':profile.get('source','FinMind')}
        if 'coverage_windows' in profile:paid['coverage_windows']=profile['coverage_windows']
    if not profile.get('payments') and profile.get('cash_paid_365d_per_share') is not None and profile.get('as_of')==str(today) and quote_ok and not data.get('corporate_action_risk'):
        details['paid_yield_pct']={'value':profile['cash_paid_365d_per_share']/price*100,
            'period_start':str(today-timedelta(days=365)+timedelta(days=1)),'period_end':str(today),
            'source':profile.get('source','FinMind'),'basis':'payment date in (today-365d, today] / latest available close',
            'price_date':str(price_date),'price':price}
    if paid and quote_ok and not data.get('corporate_action_risk') and 0<=time.time()-paid.get('fetched_at',0)<=8*86400 and paid.get('currency')==data.get('currency'):
        payments=paid.get('payments',[]);cut=str(today-timedelta(days=365))
        # Source must extend beyond window; a truncated recent table cannot prove coverage.
        from app.providers.date_windows import covers
        coverage_ok=(covers(paid['coverage_windows'],cut,str(today),now=time.time(),max_age=8*86400) if 'coverage_windows' in paid else
                     bool(payments and min(p['date'] for p in payments)<=cut))
        if coverage_ok and not any(cut<d<=str(today) for d in paid.get('splits',[])):
            amount=sum(p['amount'] for p in payments if cut<p['date']<=str(today))
            details['paid_yield_pct']={'value':amount/price*100,'period_start':str(today-timedelta(days=364)),
                'period_end':str(today),'source':paid['source'],'basis':'disclosed payable date passed / latest available close',
                'price_date':str(price_date),'price':price}
    for key in ('eps_ttm','eps_four_quarter_sum','roe_ttm_pct'):
        r=details.get(key,{})
        try:
            start=date.fromisoformat(r['period_start']);end=date.fromisoformat(r['period_end'])
            if not 330<=(end-start).days<=400 or not 0<=(today-end).days<=190 or finite(r['value']) is None:details.pop(key,None)
            if data.get('symbol','').endswith(('.TW','.TWO')):
                from app.services.ttm_proof import is_calendar_ttm
                if not is_calendar_ttm(start,end):details.pop(key,None)
        except (KeyError,ValueError,TypeError):details.pop(key,None)
    selected=details.get('eps_ttm') or details.get('eps_four_quarter_sum',{})
    data['eps']=selected.get('value')
    data['eps_basis']='four_quarter_sum' if selected and selected is details.get('eps_four_quarter_sum') else 'verified_or_reported_ttm' if selected else None
    data['eps_details']=copy.deepcopy(selected)
    data['warnings']=[w for w in data.get('warnings',[]) if not w.startswith('EPS合計口徑：')]
    if data['eps_basis']=='four_quarter_sum':
        data['warnings'].append('EPS合計口徑：近四個完整季度的原公布基本EPS相加，未統一追溯調整股數基準；與財報TTM EPS可能不同。')
    pct=details.get('roe_ttm_pct',{}).get('value');data['roe']=pct/100 if pct is not None else None
    data['yield']=details.get('paid_yield_pct',{}).get('value')
    data['yield_basis']='trailing_paid_365d' if data['yield'] is not None else None
    data['trailing_details']=details
    if data.get('kind')=='ETF':
        data['fund_profile']=profile
        data['warnings']=[w for w in data.get('warnings',[]) if not w.startswith('基本面尚缺：')]
        missing=[]
        if data['yield'] is None:missing.append('近365天已到發放日配息率')
        if data.get('expense_ratio_basis')!='annual_total_expense':missing.append('可核對的年度總費用率')
        if missing:data['warnings'].append('基本面尚缺：'+'、'.join(missing)+'；缺項不判定符合。')
        return data
    missing=[label for key,label in [('eps','EPS（缺完整近四季數值或已核對TTM）'),('roe','ROE（TTM期間）'),('yield','近365天已到發放日現金配息率')] if data.get(key) is None]
    data['warnings']=[w for w in data.get('warnings',[]) if not w.startswith('基本面尚缺：')]
    if missing:data['warnings'].append('基本面尚缺：'+'、'.join(missing)+'；不以年度或除息日數字替代。')
    for k in ('volume_ratio','volatility','expense_ratio','pe','ma20','ma60','adjusted_close'):data.setdefault(k,None)
    from app.services.analysis import enrich
    return enrich(data)
