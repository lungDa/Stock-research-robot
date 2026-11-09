"""Manual, bounded official-source check. No DB, token, scan or LINE messages."""
import argparse,json
from datetime import datetime
from zoneinfo import ZoneInfo
from app.providers.market import normalize
from app.providers.mopsfin import request,parse_catalog,parse_company,parse_annual,annual_fields,company_code


def probe(symbol,download=request):
    symbol=normalize(symbol);company_code(symbol)
    catalog=parse_catalog(download('/'))
    display=parse_company(download('/suggestCompany',params={'query':symbol.split('.')[0]}),symbol)
    values={}
    for field in ('eps','roe_pct'):
        body=download('/compare/data',form=annual_fields(field,display,catalog[field]))
        values[field]=parse_annual(body,symbol,field,display,datetime.now(ZoneInfo('Asia/Taipei')).date(),catalog[field])
    common=set(values['eps'])&set(values['roe_pct'])
    return {'symbol':symbol,'company':display,'requests':4,'source':'https://mopsfin.twse.com.tw/',
        'status':'official_annual_contract_verified','years':{field:sorted(rows) for field,rows in values.items()},
        'common_years':sorted(common),'sample':{year:{field:rows.get(year,{}).get(field) for field,rows in values.items()}
                                             for year in sorted(set().union(*[set(rows) for rows in values.values()]),reverse=True)[:5]},
        'ttm_eps_verified':False,'note':'本工作只驗證官方年度EPS與ROE；不把年度或單季值冒充TTM。'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--symbol',default='6488.TWO');args=parser.parse_args()
    try:result=probe(args.symbol)
    except Exception as exc:
        print('官方年度來源未通過驗證（'+type(exc).__name__+'）；沒有修改任何資料。')
        raise SystemExit(1)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
