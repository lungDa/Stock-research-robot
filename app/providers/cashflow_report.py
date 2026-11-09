"""Company-bound annual cash-dividend cash outflow from official cash-flow HTML."""
import re,unicodedata
from html.parser import HTMLParser
from urllib.parse import urlencode
from app.providers.mopsfin import BASE,clean
from app.providers.annual_free import finite,paid_dividend_label


def canonical(value):return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(value)))


class CashCatalog(HTMLParser):
    def __init__(self):super().__init__();self.current=None;self.items=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='a' and {'companyClass','ysoClass'}<=set(attrs.get('class','').split()):
            self.current={'code':attrs.get('name',''),'unit':attrs.get('label',''),'text':''}
    def handle_data(self,value):
        if self.current is not None:self.current['text']+=value
    def handle_endtag(self,tag):
        if tag=='a' and self.current is not None:self.items.append(self.current);self.current=None


def catalog(html):
    parser=CashCatalog();parser.feed(html)
    found={(r['code'],canonical(r['unit'])) for r in parser.items if
        canonical(r['text']).lstrip('●•·') in ('現金流量表','現金流量表(累計)') and
        re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',r['code']) and
        canonical(r['unit']) in ('','新台幣仟元','新台幣千元','新臺幣仟元','新臺幣千元')}
    if len(found)!=1:raise ValueError('Cash-flow catalog mismatch')
    code,unit=found.pop();return {'code':code,'unit':unit}


def fields(symbols,year,metric):
    codes=[s.split('.')[0] for s in symbols]
    if not 1<=len(codes)<=20 or len(set(codes))!=len(codes) or any(not re.fullmatch(r'\d{4}\.(TW|TWO)',s) for s in symbols):
        raise ValueError('Invalid cash-flow company batch')
    if not 2013<=year<=2100:raise ValueError('Invalid cash-flow year')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',metric.get('code','')):raise ValueError('Cash-flow catalog mismatch')
    if canonical(metric.get('unit','')) not in ('','新台幣仟元','新台幣千元','新臺幣仟元','新臺幣千元'):raise ValueError('Cash-flow unit mismatch')
    return {'compareItem':metric['code'],'ylabel':metric['unit'],'companyId':codes,'ys':f'{year}4',
        'quarter':'true','qnumber':'','revenue':'true','bcodeAvg':'false','companyAvg':'false'}


class ReportHTML(HTMLParser):
    """Bounded grid collector, including merged cells. Ignore script text."""
    def __init__(self):
        super().__init__();self.inputs={};self.tables=[];self.stack=[];self.cell=None;self.text=[];self.ignore=0;self.rows=0;self.divs=[];self.contexts=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ('script','style'):self.ignore+=1;return
        if self.ignore:return
        if tag=='div':self.divs.append(attrs.get('id',''))
        if tag=='input' and attrs.get('name') in ('yearseason','reportName'):
            self.inputs.setdefault(attrs['name'],set()).add(clean(attrs.get('value','')))
        if tag=='table':
            if len(self.tables)>=30 or len(self.stack)>=4:raise ValueError('Cash-flow table limit')
            table=[];self.tables.append(table);self.stack.append(table);self.contexts.append(tuple(self.divs))
        elif tag=='tr' and self.stack:
            self.rows+=1
            if self.rows>3000:raise ValueError('Cash-flow table limit')
            self.stack[-1].append([])
        elif tag in ('td','th') and self.stack and self.stack[-1]:
            try:rs=int(attrs.get('rowspan','1'));cs=int(attrs.get('colspan','1'))
            except ValueError:raise ValueError('Invalid merged cash-flow cells')
            if not 1<=rs<=30 or not 1<=cs<=32:raise ValueError('Cash-flow table limit')
            self.cell={'text':'','rs':rs,'cs':cs}
        elif tag=='br':self.handle_data(' ')
    def handle_data(self,value):
        if self.ignore:return
        self.text.append(value)
        if self.cell is not None:self.cell['text']+=value
    def handle_endtag(self,tag):
        if tag in ('script','style'):
            self.ignore=max(0,self.ignore-1);return
        if self.ignore:return
        if tag=='div' and self.divs:self.divs.pop()
        if tag in ('td','th') and self.cell is not None:
            self.stack[-1][-1].append(self.cell);self.cell=None
        if tag=='table' and self.stack:self.stack.pop()


def grid(rows):
    result=[];spans={}
    for row in rows:
        current={};future={}
        for col,(remaining,value) in spans.items():
            current[col]=value
            if remaining>1:future[col]=(remaining-1,value)
        col=0
        for cell in row:
            while col in current:col+=1
            for offset in range(cell['cs']):
                c=col+offset
                if c>=32 or c in current:raise ValueError('Invalid merged cash-flow cells')
                current[c]=clean(cell['text'])
                if cell['rs']>1:future[c]=(cell['rs']-1,current[c])
            col+=cell['cs']
        result.append([current.get(i,'') for i in range(max(current,default=-1)+1)])
        spans=future
    return result


def number(value):
    raw=canonical(value).replace('−','-')
    if raw in ('','-','--','—','NA','N/A'):return None
    if raw.startswith('(') and raw.endswith(')'):raw='-'+raw[1:-1]
    if not re.fullmatch(r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?',raw):raise ValueError('Invalid cash-flow number')
    result=finite(raw.replace(',',''))
    if result is None:raise ValueError('Invalid cash-flow number')
    return result


def parse(html,symbols,year,today,metric):
    if len(html.encode('utf-8'))>1048576:raise ValueError('Cash-flow table limit')
    if not 2013<=year<today.year:raise ValueError('Incomplete cash-flow year')
    form=fields(symbols,year,metric)
    parser=ReportHTML();parser.feed(html)
    if {value.upper().replace('Q','') for value in parser.inputs.get('yearseason',set())}!={f'{year}4'}:raise ValueError('Cash-flow report period mismatch')
    names=parser.inputs.get('reportName',set())
    if not names:raise ValueError('Not a cash-flow statement')
    unit_text=unicodedata.normalize('NFKC',' '.join(parser.text))
    units={canonical(value) for value in re.findall(r'金額\s*單位\s*[:：]\s*([^()<>，,\s]+)',unit_text)}
    if len(units)!=1 or not units<= {'新台幣仟元','新台幣千元','新臺幣仟元','新臺幣千元'}:
        raise ValueError('Cash-flow unit mismatch')
    all_rows=[grid(table) for table in parser.tables]
    # Official HTML uses two sibling tables: row labels and company values.
    # Only join the explicitly identified containers with equal row counts.
    heads=[i for i,c in enumerate(parser.contexts) if 'headTable' in c]
    bodies=[i for i,c in enumerate(parser.contexts) if 'bodyTable' in c]
    split=False
    if heads or bodies:
        if len(heads)!=1 or len(bodies)!=1:raise ValueError('Cash-flow split table mismatch')
        labels=all_rows[heads[0]];values=all_rows[bodies[0]]
        if len(labels)!=len(values) or len(labels)<3 or any(len(r)!=1 for r in labels):raise ValueError('Cash-flow split table mismatch')
        if labels[0]!=['報表類別'] or labels[1]!=['會計科目']:raise ValueError('Cash-flow split table mismatch')
        width=len(values[1])
        if not width or any(len(r)!=width for r in values):raise ValueError('Cash-flow split table mismatch')
        sections={canonical(r[0]) for r in labels}
        if not all(kind+'活動之淨現金流入(流出)' in sections for kind in ('營業','投資','籌資')):raise ValueError('Not a cash-flow statement')
        if names!={clean(v) for v in values[1]}:raise ValueError('Cash-flow company metadata mismatch')
        all_rows=[[left+right for left,right in zip(labels,values)]];split=True
    if not split and any('現金流量表' not in name for name in names):raise ValueError('Not a cash-flow statement')
    source_url=BASE+'/compare/report?'+urlencode(form,doseq=True)
    results={};issues={}
    for symbol in symbols:
        code=symbol.split('.')[0];matches=[];found_company=False;scope_issue=False
        for rows in all_rows:
            first_item=next((i for i,r in enumerate(rows) if any(paid_dividend_label(c) for c in r)),len(rows))
            if first_item==len(rows):continue
            headers=rows[:first_item];width=max(map(len,headers),default=0)
            cols=[]
            for col in range(width):
                cells=[r[col] for r in headers if col<len(r)]
                text=' '.join(cells)
                # Each value column must belong to exactly this company.
                # Match within a cell: joining a numeric row with the next dash
                # must not manufacture an extra company identifier.
                identities={number for cell in cells for number,name in re.findall(
                    r'(?<!\d)(\d{4})\s+([A-Za-z\u3400-\u9fff][^\s]*)',cell)
                    if name not in ('年','年度','元','仟元','千元','TWD','NTD','USD') and not re.fullmatch(r'Q[1-4]',name)}
                if identities!={code}:continue
                if ('上市' in text and symbol.endswith('.TWO')) or ('上櫃' in text and symbol.endswith('.TW')):continue
                found_company=True
                if '合併' not in text or '個體' in text or '個別' in text:scope_issue=True;continue
                cols.append(col)
            if len(cols)>1:raise ValueError('Ambiguous cash-flow company columns')
            if not cols:continue
            col=cols[0]
            for row in rows[first_item:]:
                labels=[(i,c) for i,c in enumerate(row) if paid_dividend_label(c)]
                if len(labels)!=1 or col>=len(row) or col<=labels[0][0]:continue
                value=number(row[col])
                if value is not None:
                    normalized=abs(value)*1000
                    if finite(normalized) is None:raise ValueError('Invalid cash-flow number')
                    matches.append((normalized,value,labels[0][1]))
        if not matches:
            issues[symbol]='報表未明列可核對的現金股利支出（不以空白或破折號補0）' if found_company and not scope_issue else '尚無已核對的合併範圍／公司欄位'
            continue
        if len({m[0] for m in matches})!=1:
            issues[symbol]='現金股利支出有衝突數值，保留原資料';continue
        value,signed,label=matches[0]
        evidence={'provenance':'MOPSFIN_cash_flow_annual','url':source_url,'as_of':str(today),
            'period_start':f'{year}-01-01','period_end':f'{year}-12-31','unit':'TWD',
            'reported_unit':next(iter(units)),'reported_value':signed,'multiplier':1000,
            'label':label,'scope':'consolidated','basis':'reported_full_year_cash_dividend_outflow',
            'request':form}
        results[symbol]={'cash_dividends_paid':value,'cash_dividends_paid_basis':'reported full-year consolidated cash-flow outflow; TWD',
            'currency':'TWD','period_start':f'{year}-01-01','period_end':f'{year}-12-31',
            'source_url':source_url,'provenance':'MOPSFIN_cash_flow_annual','as_of':str(today),
            'field_sources':{'cash_dividends_paid':evidence}}
    return results,issues
