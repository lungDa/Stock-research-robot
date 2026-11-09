"""Official MOPS Financial Comparison annual series, for both TWSE and TPEx.

Use cumulative Q4, not Q4 single-quarter values or quarterly ratio averages.
Request and response identity, units, periods and numeric values are validated.
No arbitrary URLs, retries, cookies, or credentials are accepted.
"""
import json,math,re,time,unicodedata
from datetime import date
from html.parser import HTMLParser
import requests

BASE='https://mopsfin.twse.com.tw'
METRICS={'eps':('EPS','每股盈餘','元'),'roe_pct':('ROE','權益報酬率','%')}


def clean(value):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(value))).strip()


def company_code(symbol):
    if not re.fullmatch(r'\d{4}\.(TW|TWO)',symbol):raise ValueError('Only Taiwan common-stock symbols are supported')
    return symbol.split('.')[0]


class Catalog(HTMLParser):
    def __init__(self):super().__init__();self.active=None;self.entries=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='a' and 'compareClass' in attrs.get('class','').split():
            self.active={'code':attrs.get('name'),'unit':clean(attrs.get('label','')),'text':''}
    def handle_data(self,data):
        if self.active is not None:self.active['text']+=data
    def handle_endtag(self,tag):
        if tag=='a' and self.active is not None:
            self.entries.append(self.active);self.active=None


def parse_catalog(html):
    parser=Catalog();parser.feed(html);result={}
    for field,(code,label,unit) in METRICS.items():
        candidates={(row['code'],row['unit']) for row in parser.entries
            if clean(row['text']).lstrip('●•· ').replace(' ','')==label and row['unit']==unit
            and isinstance(row['code'],str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',row['code'])}
        if len(candidates)!=1:raise ValueError('Official catalog contract changed')
        actual_code,actual_unit=candidates.pop()
        result[field]={'code':actual_code,'unit':actual_unit,'label':label}
    return result


def parse_company(payload,symbol):
    code=company_code(symbol)
    if not isinstance(payload,dict) or not isinstance(payload.get('suggestions'),list):raise ValueError('Invalid company lookup')
    matches={clean(s) for s in payload['suggestions'] if isinstance(s,str) and re.fullmatch(re.escape(code)+r'\s+\S.*',clean(s))}
    if len(matches)!=1:raise ValueError('Company identity missing or ambiguous')
    return matches.pop()


def annual_fields(field,display,metric=None):
    if field not in METRICS or not re.fullmatch(r'\d{4}\s+\S.*',display):raise ValueError('Invalid annual series request')
    code,_,unit=METRICS[field]
    if metric is not None:
        if metric.get('unit')!=unit or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',metric.get('code','')):raise ValueError('Invalid catalog metric')
        code=metric['code']
    return {'compareItem':code,'ylabel':unit,'companyId':display,'quarter':'false','qnumber':'4',
            'ys':'0','revenue':'true','bcodeAvg':'false','companyAvg':'false'}


def number(value):
    if value is None or isinstance(value,bool):return None
    if isinstance(value,str):
        value=clean(value)
        if value.upper() in ('','-','--','N/A','NA','NULL'):return None
        if not re.fullmatch(r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?',value):raise ValueError('Invalid numeric value')
        value=value.replace(',','')
    if type(value) not in (int,float,str):raise ValueError('Invalid numeric type')
    result=float(value)
    if not math.isfinite(result):raise ValueError('Nonfinite annual value')
    return result


def parse_annual(payload,symbol,field,display,today,metric=None):
    company_code(symbol)
    if field not in METRICS or not isinstance(payload,dict):raise ValueError('Invalid annual response')
    if payload.get('message'):raise ValueError('No annual data')
    if clean(payload.get('ylabel',''))!=METRICS[field][2]:raise ValueError('Annual unit mismatch')
    if payload.get('quarter') in (True,1,'1','true','True') or str(payload.get('qnumber','4')) not in ('4','04'):raise ValueError('Not cumulative Q4')
    axes=payload.get('xaxisList');graph=payload.get('graphData')
    if not isinstance(axes,list) or not 1<=len(axes)<=100 or len(set(map(str,axes)))!=len(axes):raise ValueError('Invalid annual periods')
    if not isinstance(graph,list) or len(graph)!=1 or not isinstance(graph[0],dict):raise ValueError('Unexpected company or average series')
    series=graph[0]
    code=company_code(symbol)
    aliases={display,display.split(' ',1)[1],code}
    label=clean(series.get('label',''))
    if label not in aliases:raise ValueError('Company series does not match verified identity')
    code_verified=label in (display,code)
    for key in ('displayCompanyId','checkedNameList'):
        values=payload.get(key)
        if values in (None,[]):continue
        if not isinstance(values,list) or len(values)!=1 or clean(values[0]) not in aliases:raise ValueError('Company identity metadata mismatch')
        code_verified=code_verified or clean(values[0]) in (code,display)
    if not code_verified:raise ValueError('Company code cannot be bound to this series')
    if payload.get('extraNameList'):raise ValueError('Average series must not be used')
    years=[]
    for axis in axes:
        match=re.fullmatch(r'(20\d{2})Q4',str(axis))
        if not match:raise ValueError('Expected full-year Q4 cumulative periods')
        years.append(int(match[1]))
    points=series.get('data')
    if not isinstance(points,list) or len(points)>100:raise ValueError('Invalid annual points')
    rows={};seen=set()
    for point in points:
        if not isinstance(point,list) or len(point)<2:raise ValueError('Invalid point index')
        raw_index=point[0]
        if isinstance(raw_index,bool) or type(raw_index) not in (int,float,str):raise ValueError('Invalid point index')
        if isinstance(raw_index,str) and not re.fullmatch(r'\d+',raw_index):raise ValueError('Invalid point index')
        try:index=int(raw_index)
        except (ValueError,OverflowError):raise ValueError('Invalid point index')
        if not isinstance(raw_index,str) and index!=raw_index:raise ValueError('Invalid point index')
        if not 0<=index<len(years) or index in seen:raise ValueError('Duplicate or invalid period index')
        seen.add(index);year=years[index];value=number(point[1])
        if value is None or not max(2013,today.year-11)<=year<today.year:continue
        basis='reported_full_year_EPS; cumulative_Q4' if field=='eps' else 'reported_annual_financial_analysis_ROE; cumulative_Q4'
        source={'url':BASE+'/','route':'/compare/data','provenance':'MOPSFIN_annual',
                'as_of':str(today),'period_start':f'{year}-01-01','period_end':f'{year}-12-31',
                'unit':'TWD_PER_SHARE' if field=='eps' else 'PERCENT_POINTS','basis':basis,
                'request':annual_fields(field,display,metric)}
        rows[str(year)]={field:value,'currency':'TWD','period_start':f'{year}-01-01','period_end':f'{year}-12-31',
            'source_url':BASE+'/','provenance':'MOPSFIN_annual','as_of':str(today),
            'field_sources':{field:source},'notes':['官方第4季累計／全年口徑；不是第4季單季數值，亦非TTM。']}
    if not rows:raise ValueError('No usable completed annual periods')
    return rows


def request(path,*,params=None,form=None):
    if path not in ('/','/suggestCompany','/compare/data'):raise ValueError('Nonallowlisted path')
    if (path=='/compare/data')!=(form is not None):raise ValueError('Invalid method for official path')
    start=time.monotonic();chunks=[];size=0
    headers={'Accept':'application/json,text/html','User-Agent':'Stock-Lighthouse/2.0'}
    if form is not None:
        headers.update({'Origin':BASE,'Referer':BASE+'/','X-Requested-With':'XMLHttpRequest'})
    with requests.request('POST' if form is not None else 'GET',BASE+path,params=params,data=form,
                          headers=headers,timeout=(2,2),stream=True,allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code!=200:raise ValueError('No direct successful response')
        for chunk in response.iter_content(8192):
            size+=len(chunk)
            if size>1048576 or time.monotonic()-start>6:raise ValueError('Official response exceeds budget')
            chunks.append(chunk)
    raw=b''.join(chunks).decode('utf-8-sig')
    return raw if path=='/' else json.loads(raw)
