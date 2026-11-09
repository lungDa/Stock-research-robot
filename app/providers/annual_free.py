"""Free annual fundamentals. Network access is reserved for the bounded worker.
Never infer missing distributions, combine quarterly EPS, or substitute investing
cash flow for capital expenditure. Shared data never overwrites private imports.
"""
import math, re, unicodedata
from datetime import date, timedelta

FINMIND = 'https://api.finmindtrade.com/api/v4/data'
SEC = 'https://data.sec.gov/api/xbrl/companyconcept/'
TW_DATASETS = ('TaiwanStockFinancialStatements', 'TaiwanStockBalanceSheet',
               'TaiwanStockCashFlowsStatement', 'TaiwanStockDividend', 'TaiwanStockPrice')
TW_CASH_SCHEMA = 3

def paid_dividend_label(label):
    label=re.sub(r'\s+','',unicodedata.normalize('NFKC',str(label)))
    # Exact cash-flow totals only; do not include non-controlling dividends,
    # declared policies, payable balances, or interest/dividend combined lines.
    return label in {'支付之股利','發放現金股利','支付股利','支付現金股利',
        '支付之現金股利','現金股利之支付','發放股利','分配股利','發放現金股利數',
        '分配現金股利','現金股利之發放','支付予本公司業主之股利',
        '支付予母公司業主之股利','支付予業主之股利'}

def paid_dividend_total(records,code,end):
    matches=[finite(r.get('value')) for r in records if str(r.get('stock_id'))==code
        and r.get('date')==end and paid_dividend_label(r.get('origin_name',''))]
    if not matches or any(v is None for v in matches):return None
    # Same line may appear twice. Conflicting totals are not added together.
    values={abs(v) for v in matches}
    return values.pop() if len(values)==1 else None
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
    events={}; all_events={};splits=[];code=symbol.split('.')[0]
    for r in records:
        d=valid_day(r.get('CashDividendPaymentDate'))
        if str(r.get('stock_id'))!=code or not d:continue
        a=finite(r.get('CashEarningsDistribution')); b=finite(r.get('CashStatutorySurplus'))
        if a is None or b is None or min(a,b)<0:continue
        key=(str(d),r.get('year'),r.get('CashExDividendTradingDate'))
        if key in all_events and all_events[key]!=a+b:return {}
        all_events[key]=a+b
        stock_a=finite(r.get('StockEarningsDistribution'));stock_b=finite(r.get('StockStatutorySurplus'))
        split_date=valid_day(r.get('StockExDividendTradingDate'))
        if split_date and ((stock_a or 0)>0 or (stock_b or 0)>0):splits.append(str(split_date))
        if not today-timedelta(days=365)<d<=today:continue
        if key in events and events[key]!=a+b:return {}
        events[key]=a+b
    if not events:return {}
    return {'cash_paid_365d_per_share':sum(events.values()),'as_of':today.isoformat(),
        'payments':[{'date':k[0],'amount':v} for k,v in all_events.items()], 'splits':splits,'currency':'TWD',
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


def taiwan_rows(symbol, feeds, today, coverage=None):
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
            row(y)['field_sources']={'roe_pct':{'url':'https://finmind.github.io/tutor/TaiwanMarket/Fundamental/',
                'provenance':'FinMind_derived','as_of':str(today),'unit':'PERCENT_POINTS',
                'period_start':f'{y}-01-01','period_end':end,
                'basis':'full_year_total_net_income / mean opening and closing total equity',
                'calculation':{'net_income':ni,'opening_equity':prev,'closing_equity':eq,'mean_equity':(eq+prev)/2,
                               'quarter_ends':quarters,'scope':'total_consolidated_income_and_equity','currency':'TWD'}}}
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
        paid=paid_dividend_total(feeds.get(TW_DATASETS[2],[]),code,end)
        if paid is not None:
            row(y)['cash_dividends_paid']=paid
            row(y)['cash_dividends_paid_basis']='calendar_year_paid_cash_flow; TWD'
            row(y).setdefault('field_sources',{})['cash_dividends_paid']={
                'url':FINMIND+'?dataset='+TW_DATASETS[2]+'&data_id='+code+'&start_date='+end+'&end_date='+end,
                'provenance':'FinMind_cash_flow_annual','as_of':str(today),'unit':'TWD',
                'period_start':f'{y}-01-01','period_end':end,'basis':'reported_Q4_year_to_date_cash_dividend_outflow',
                'labels':sorted({str(r.get('origin_name','')) for r in feeds.get(TW_DATASETS[2],[])
                    if str(r.get('stock_id'))==code and r.get('date')==end and paid_dividend_label(r.get('origin_name',''))})}
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
        from app.providers.date_windows import covers
        if coverage is not None and TW_DATASETS[3] in coverage and not covers(coverage[TW_DATASETS[3]],f'{y}-01-01',f'{y}-12-31'):continue
        row(y)['cash_dividend_per_share']=total
        row(y)['dividend_basis']='payment_date; no missing year assumed zero'
        if y in prices and prices[y][0].month==12:
            if coverage is not None and TW_DATASETS[4] in coverage and not covers(coverage[TW_DATASETS[4]],f'{y}-12-01',f'{y}-12-31'):continue
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
