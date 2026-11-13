"""LINE Flex carousel for ranked Taiwan-stock recommendations.

Only render validated URLs and bounded text; delivery remains the caller's job.
"""
from urllib.parse import urlencode,urlsplit

def _https_origin(url):
    try:
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.port not in (None,443):
            return None
        return 'https://'+parsed.hostname+(parsed.path.rstrip('/') if parsed.path not in ('','/') else '')
    except (ValueError,TypeError):
        return None

def _text(value,limit=70):
    return str(value if value is not None else '未提供').replace('\n',' ').replace('\r',' ')[:limit]

def recommendation_flex(items,app_url):
    """Build one LINE Flex carousel with at most ten independently labelled picks.

    Returns None for empty items or an invalid application URL.
    The URL intentionally does not include sensitive account data.
    """
    origin=_https_origin(app_url)
    if not origin or not items:
        return None
    bubbles=[]
    for index,item in enumerate(items[:10],1):
        symbol=_text(item.get('symbol',''),24)
        if not symbol or symbol=='未提供':
            continue
        label=_text(item.get('name') or symbol,45)
        score=_text(item.get('score'),12)
        tier=_text(item.get('relaxation_round',item.get('round','未提供')),12)
        detail=origin+('?' if '?' not in origin else '&')+urlencode({'symbol':symbol})
        bubble={'type':'bubble','size':'kilo',
                'body':{'type':'box','layout':'vertical','spacing':'md','contents':[
                    {'type':'text','text':f'第 {index} 名｜{label}','weight':'bold','size':'md','wrap':True},
                    {'type':'text','text':symbol,'size':'sm','color':'#666666'},
                    {'type':'text','text':f'規則分數：{score}｜放寬輪次：{tier}','size':'sm','wrap':True},
                    {'type':'text','text':'資料不足或放寬條件不代表保證報酬','size':'xs','wrap':True,'color':'#777777'}]},
                'footer':{'type':'box','layout':'vertical','spacing':'sm','contents':[
                    {'type':'button','style':'primary','action':{'type':'uri','label':'詳細分析','uri':detail}},
                    {'type':'button','style':'secondary','action':{'type':'uri','label':'開啟股海燈塔','uri':origin}}]}}
        bubbles.append(bubble)
    if not bubbles:return None
    return {'type':'flex','altText':f'股海燈塔｜前 {len(bubbles)} 名股票推薦',
            'contents':{'type':'carousel','contents':bubbles}}
