"""Manual, bounded official-source check. No DB, token, scan or LINE messages."""
import argparse,json,re
from datetime import datetime
from zoneinfo import ZoneInfo
from app.providers.market import normalize
from app.providers.mopsfin import request,parse_catalog,parse_company,parse_annual,annual_fields,company_code,clean


def probe(symbol,download=request):
    symbol=normalize(symbol);company_code(symbol)
    catalog=parse_catalog(download('/'))
    display=parse_company(download('/suggestCompany',params={'query':symbol.split('.')[0]}),symbol)
    values={}
    errors = []
    for field in ('eps','roe_pct'):
        body=download('/compare/data',form=annual_fields(field,display,catalog[field]))
        try:
            values[field]=parse_annual(body,symbol,field,display,datetime.now(ZoneInfo('Asia/Taipei')).date(),catalog[field])
        except ValueError as exc:
            def profile(value):
                normalized = clean(value)
                alias = display.split(' ', 1)[1]
                prefix = re.match(r'^([0-9]{4})(?![0-9])', normalized)
                return {'type': type(value).__name__,
                        'matches_display': normalized == display,
                        'matches_name': normalized == alias,
                        'matches_code': normalized == symbol.split('.')[0],
                        'code_prefix': prefix.group(1) if prefix else None,
                        'separator': 'space' if prefix and normalized[4:5] == ' ' else
                                     'other' if prefix and normalized[4:] else 'none'}
            items = {}
            for key in ('displayCompanyId', 'checkedNameList'):
                raw = body.get(key)
                items[key] = [profile(value) for value in raw[:2]] if isinstance(raw, list) else {'type': type(raw).__name__}
            items['graph_labels'] = [profile(item.get('label')) for item in body.get('graphData', [])[:2]]
            errors.append({'field': field, 'error': str(exc), 'metadata': items})
    if errors:
        print(json.dumps({'symbol': symbol, 'diagnosis': errors}, ensure_ascii=False))
        raise ValueError('Official response failed the contract')
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
