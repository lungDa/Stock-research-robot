"""Free annual fundamentals. Network access is reserved for the bounded worker.
Never infer missing distributions, combine quarterly EPS, or substitute investing
cash flow for capital expenditure. Shared data never overwrites private imports.
"""
import math
from datetime import date, timedelta

FINMIND = 'https://api.finmindtrade.com/api/v4/data'
SEC = 'https://data.sec.gov/api/xbrl/companyconcept/'
TW_DATASETS = ('TaiwanStockFinancialStatements', 'TaiwanStockBalanceSheet',
               'TaiwanStockCashFlowsStatement', 'TaiwanStockDividend', 'TaiwanStockPrice')
# Separate concepts keep each request small; aliases rotate independently.
SEC_CONCEPTS = {
 'eps': ('EarningsPerShareDiluted', 'USD/shares'),
 'net_income': ('NetIncomeLoss', 'USD'),
 'equity': ('StockholdersEquity', 'USD'),
 'operating_cash_flow': ('NetCashProvidedByUsedInOperatingActivities', 'USD'),
 'capital_expenditure': ('PaymentsToAcquirePropertyPlantAndEquipment', 'USD'),
 'cash_dividends_paid': ('PaymentsOfDividendsCommonStock', 'USD'),
 'cash_dividend_per_share': ('CommonStockDividendsPerShareDeclared', 'USD/shares'),
 'revenue': ('RevenueFromContractWithCustomerExcludingAssessedTax', 'USD'),
 'revenue_legacy': ('Revenues', 'USD'),
}


def finite(value):
    if isinstance(value, bool): return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError): return None


def valid_day(value):
    try: return date.fromisoformat(str(value))
    except (ValueError, TypeError): return None


def taiwan_fund_profile(symbol, records, today):
    """Distributions whose disclosed payment date has passed; never announced yield."""
    events={}; code=symbol.split('.')[0]
    for r in records:
        d=valid_day(r.get('CashDividendPaymentDate'))
        if str(r.get('stock_id'))!=code or not d or not today-timedelta(days=365)<d<=today:continue
        a=finite(r.get('CashEarningsDistribution')); b=finite(r.get('CashStatutorySurplus'))
        if a is None or b is None or min(a,b)<0:continue
        key=(str(d),r.get('year'),r.get('CashExDividendTradingDate'))
        if key in events and events[key]!=a+b:return {}
        events[key]=a+b
    if not events:return {}
    return {'cash_paid_365d_per_share':sum(events.values()),'as_of':today.isoformat(),
        'source':'FinMind / TaiwanStockDividend','basis':'disclosed_payment_date_passed',
        'note':'依公告發放日計算；來源未涵蓋或不適用時留白，不以宣告殖利率替代'}


def tw_series(records, code):
    grouped = {}
    for r in records:
        d = valid_day(r.get('date')); v = finite(r.get('value'))
        if str(r.get('stock_id')) != code or d is None or v is None: continue
        key = (str(d), r.get('type'))
        # Conflicting duplicates are discarded instead of arbitrarily added.
        if key in grouped and grouped[key] != v: grouped[key] = None
        else: grouped.setdefault(key, v)
    return grouped


def taiwan_rows(symbol, feeds, today):
    code = symbol.split('.')[0]; rows = {}
    def row(year):
        return rows.setdefault(str(year), {'currency':'TWD', 'provenance':'FinMind',
            'source_url':'https://finmind.github.io/tutor/TaiwanMarket/Fundamental/',
            'as_of':today.isoformat(), 'period_basis':'calendar_year', 'notes':[]})
    income = tw_series(feeds.get(TW_DATASETS[0], []), code)
    balance = tw_series(feeds.get(TW_DATASETS[1], []), code)
    cash = tw_series(feeds.get(TW_DATASETS[2], []), code)
    for y in range(today.year - 11, today.year):
        quarters = [f'{y}-{s}' for s in ('03-31','06-30','09-30','12-31')]
        for field, tag in [('revenue','Revenue'), ('net_income','IncomeAfterTaxes')]:
            vals = [income.get((d, tag)) for d in quarters]
            if all(v is not None for v in vals): row(y)[field] = sum(vals)
        # FinMind EPS uses potentially inconsistent quarterly share bases.
        # Keep missing; an official Q4 annual figure or private annual import can fill it.
        end = f'{y}-12-31'
        eq = balance.get((end,'Equity')); prev = balance.get((f'{y-1}-12-31','Equity'))
        ni = rows.get(str(y),{}).get('net_income')
        if ni is not None and eq is not None and prev is not None and min(eq,prev)>0:
            row(y)['roe_pct'] = ni / ((eq+prev)/2) * 100
        for field, tag in [('operating_cash_flow','CashFlowsFromOperatingActivities'),
                           ('capital_expenditure','PropertyAndPlantAndEquipment')]:
            val = cash.get((end,tag))
            if val is not None:
                # Acquisition cash outflow is negative in this source.
                if field == 'capital_expenditure':
                    if val > 0: continue
                    val = -val
                row(y)[field] = val
        # Only an explicitly named paid cash-flow line, never policy × shares.
        for tag in ('支付之股利','發放現金股利'):
            matched = [r for r in feeds.get(TW_DATASETS[2],[]) if r.get('date')==end
                       and str(r.get('stock_id'))==code and r.get('origin_name')==tag]
            if len(matched)==1 and finite(matched[0].get('value')) is not None:
                row(y)['cash_dividends_paid'] = abs(float(matched[0]['value']))
    seen = {}; payments = {}
    for r in feeds.get(TW_DATASETS[3],[]):
        d = valid_day(r.get('CashDividendPaymentDate'))
        if str(r.get('stock_id')) != code or not d or d>today: continue
        a=finite(r.get('CashEarningsDistribution')); b=finite(r.get('CashStatutorySurplus'))
        if a is None or b is None or min(a,b)<0: continue
        key=(r.get('year'),str(d),r.get('CashExDividendTradingDate'))
        if key in seen:
            if seen[key] != a+b: payments[d.year] = None
            continue
        seen[key]=a+b
        if d.year not in payments: payments[d.year]=0.0
        if payments[d.year] is not None: payments[d.year]+=a+b
    prices = {}
    for r in feeds.get(TW_DATASETS[4],[]):
        d=valid_day(r.get('date')); v=finite(r.get('close'))
        if str(r.get('stock_id'))!=code or not d or not v or v<=0 or d>today: continue
        if d.year not in prices or d>prices[d.year][0]: prices[d.year]=(d,v)
    for y,total in payments.items():
        if y>=today.year or total is None: continue
        row(y)['cash_dividend_per_share']=total
        row(y)['dividend_basis']='payment_date; no missing year assumed zero'
        if y in prices and prices[y][0].month==12:
            row(y)['cash_yield_pct']=total/prices[y][1]*100
            row(y)['yield_basis']='paid_calendar_year / unadjusted_year_end_close'
    # The source cannot prove quarterly EPS compatibility, so expose the reason.
    for r in rows.values(): r['notes'].append('年度EPS未直接加總單季值；須官方年報或年度CSV補齊')
    return rows


def sec_records(payload, metric, today):
    tag,unit=SEC_CONCEPTS[metric]
    if payload.get('tag') != tag or payload.get('taxonomy')!='us-gaap': return {}
    result={}
    for r in payload.get('units',{}).get(unit,[]):
        end=valid_day(r.get('end')); filed=valid_day(r.get('filed')); val=finite(r.get('val'))
        if not end or not filed or filed>today or end>=today or val is None: continue
        if metric in ('capital_expenditure','cash_dividends_paid') and val<0: continue
        if r.get('form') not in ('10-K','10-K/A'): continue
        if metric!='equity':
            start=valid_day(r.get('start'))
            if not start or not 330<=(end-start).days<=400: continue
        else: start=None
        key=str(end)
        if key not in result or filed.isoformat()>result[key]['filed']:
            result[key]={'value':val,'start':str(start) if start else None,
                'end':str(end),'filed':str(filed),'accession':r.get('accn','')}
    return result


def us_rows(cik, concepts, today):
    rows={}
    # One annual report window per end-year. Never add overlapping SEC facts.
    ends=sorted({e for records in concepts.values() for e in records}, reverse=True)
    used=set()
    for end in ends:
        y=int(end[:4])
        if y>=today.year or y<today.year-11 or y in used: continue
        anchor=next((concepts.get(m,{}).get(end) for m in ('eps','revenue','revenue_legacy','net_income')
                     if concepts.get(m,{}).get(end)),None)
        if not anchor: continue
        used.add(y)
        r={'currency':'USD','provenance':'SEC_10K','source_url':f'https://www.sec.gov/edgar/browse/?CIK={cik}',
           'period_basis':'fiscal_year_end','period_start':anchor['start'],'period_end':end,
           'as_of':today.isoformat(),'notes':['EPS門檻以USD計；年度依會計年度結束年標示']}
        for metric in SEC_CONCEPTS:
            record=concepts.get(metric,{}).get(end)
            if not record or record['start']!=anchor['start']: continue
            if metric=='cash_dividend_per_share':
                # Declared is not paid. Preserve for inspection only.
                r['declared_dividend_per_share']=record['value']; continue
            name='revenue' if metric=='revenue_legacy' else metric
            if name not in r: r[name]=record['value']
        eq=concepts.get('equity',{}).get(end)
        prev=[v for e,v in concepts.get('equity',{}).items()
              if 330<=(date.fromisoformat(end)-date.fromisoformat(e)).days<=400]
        if eq and len(prev)==1 and 'net_income' in r and min(eq['value'],prev[0]['value'])>0:
            r['roe_pct']=r['net_income']/((eq['value']+prev[0]['value'])/2)*100
        rows[str(y)]=r
    return rows
