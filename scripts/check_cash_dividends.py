"""Two bounded, read-only official requests; no database or token required."""
import argparse,json,re
from app.providers.market import normalize
from app.providers.mopsfin import request
from app.providers.cashflow_report import catalog,fields,parse,ReportHTML,grid
from app.providers.source_errors import describe
from app.services.freshness import local_now


def probe(symbols,year,download=request):
    symbols=[normalize(s) for s in symbols]
    if not symbols or len(symbols)>20 or len({s.split('.')[0] for s in symbols})!=len(symbols) or any(not re.fullmatch(r'\d{4}\.(TW|TWO)',s) for s in symbols):raise ValueError('Invalid cash-flow company batch')
    today=local_now().date()
    if not 2013<=year<today.year:raise ValueError('Incomplete cash-flow year')
    count=0;stage='現金流量表目錄';html=''
    try:
        count+=1;metric=catalog(download('/'))
        stage='年度現金流量表下載';count+=1
        html=download('/compare/report',form=fields(symbols,year,metric))
        stage='年度現金流量表解析';values,issues=parse(html,symbols,year,today,metric)
        result={'state':'verified' if len(values)==len(symbols) else 'partial','cash_requests':count,
            'year':year,'symbols':symbols,'rows':values,'issues':issues,'database_written':False}
    except Exception as exc:
        result={'state':'failed','cash_requests':count,'symbols':symbols,'year':year,'database_written':False,**describe(exc,stage)}
    if html:
        try:
            parser=ReportHTML();parser.feed(html)
            headers=[]
            for table in parser.tables:
                for row in grid(table)[:6]:
                    headers.extend(cell[:120] for cell in row if any(re.search(r'(?<!\d)'+s.split('.')[0]+r'(?!\d)',cell) for s in symbols))
            result['observed']={'period':sorted(parser.inputs.get('yearseason',set())),
                'report_names':sorted(parser.inputs.get('reportName',set())),'company_headers':list(dict.fromkeys(headers))[:20]}
        except Exception:pass
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--symbols',default='2330.TW,2412.TW,6488.TWO,2886.TW')
    parser.add_argument('--year',type=int,default=local_now().year-1);args=parser.parse_args()
    result=probe([s.strip() for s in args.symbols.split(',') if s.strip()],args.year)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['state']!='verified':raise SystemExit(1)
