"""規則篩選：不是預測報酬，缺值不補零。"""
def evaluate(data,mode):
    checks={}
    if mode=='swing':
        checks={'站上20日均線':None if data.get('ma20') is None else data['adjusted_close']>data['ma20'],
                '20日均線高於60日':None if data.get('ma20') is None or data.get('ma60') is None else data['ma20']>data['ma60'],
                '成交量達20日均量':None if data['volume_ratio'] is None else data['volume_ratio']>=1}
    elif mode=='income':
        if data['kind']=='ETF':
            checks={'近一年配息率達3%':None if data['yield'] is None else data['yield']>=3,
                    '年化波動低於25%':None if data['volatility'] is None else data['volatility']<25,
                    '費用率低於0.5%':None if data['expense_ratio'] is None else data['expense_ratio']<.005}
        elif data['kind']=='STOCK':
            checks={'EPS為正':None if data['eps'] is None else data['eps']>0,
                    'ROE達15%':None if data['roe'] is None else data['roe']>=.15,
                    '近一年配息率達3%':None if data['yield'] is None else data['yield']>=3,
                    '本益比介於0至25':None if data['pe'] is None else 0<data['pe']<=25}
        else: checks={'商品種類可辨識':None}
    else: raise ValueError('未知模式')
    return {'mode':mode,'score':sum(v is True for v in checks.values()),'total':len(checks),
            'matched':all(v is True for v in checks.values()),'checks':checks}

def enrich(data):
    return {**data,'income':evaluate(data,'income'),'swing':evaluate(data,'swing')}
