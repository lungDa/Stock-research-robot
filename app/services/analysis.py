"""規則篩選：不是預測報酬，缺值不補零。"""
def evaluate(data,mode):
    checks={}
    if mode=='swing':
        checks={'站上20日均線':None if data.get('ma20') is None or data.get('adjusted_close') is None else data.get('adjusted_close')>data['ma20'],
                '20日均線高於60日':None if data.get('ma20') is None or data.get('ma60') is None else data['ma20']>data['ma60'],
                '成交量達20日均量':None if data.get('volume_ratio') is None else data.get('volume_ratio')>=1}
    elif mode=='income':
        if data.get('kind')=='ETF':
            checks={'近一年配息率達3%':None if data.get('yield') is None else data.get('yield')>=3,
                    '年化波動低於25%':None if data.get('volatility') is None else data.get('volatility')<25,
                    '費用率低於0.5%':None if data.get('expense_ratio') is None else data.get('expense_ratio')<.005}
        elif data.get('kind')=='STOCK':
            checks={'EPS為正':None if data.get('eps') is None else data.get('eps')>0,
                    'ROE達15%':None if data.get('roe') is None else data.get('roe')>=.15,
                    '近一年配息率達3%':None if data.get('yield') is None else data.get('yield')>=3,
                    '本益比介於0至25':None if data.get('pe') is None else 0<data.get('pe')<=25}
        else: checks={'商品種類可辨識':None}
    else: raise ValueError('未知模式')
    from app.services.freshness import market_usable
    if not market_usable(data):checks={label:None for label in checks}
    if mode=='income' and data.get('kind')=='ETF':
        if data.get('yield_basis')!='trailing_paid_365d':checks['近一年配息率達3%']=None
        if data.get('expense_ratio_basis')!='annual_total_expense':checks['費用率低於0.5%']=None
    return {'mode':mode,'score':sum(v is True for v in checks.values()),'total':len(checks),
            'matched':all(v is True for v in checks.values()),'checks':checks}

def enrich(data):
    return {**data,'income':evaluate(data,'income'),'swing':evaluate(data,'swing')}
