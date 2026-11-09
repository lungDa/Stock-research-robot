"""Explain absent fields without claiming that more retries can fill every gap."""
import os,time
from app.services.freshness import local_now


def report(data,rows,rating,read):
    symbol=data['symbol'];tw=symbol.endswith(('.TW','.TWO'));today=local_now().date()
    source='finmind' if tw else 'sec'
    cooling=read('annual:source:'+source,{}).get('next_attempt',0)>time.time()
    configured=bool(os.getenv('FINMIND_TOKEN' if tw else 'SEC_USER_AGENT','').strip())
    batch=read('annual:query_result:'+symbol,{})
    queued=batch.get('state') in ('queued','running') and time.time()-batch.get('at',0)<300
    labels=[]
    for check in rating.get('checks',[]):
        metric=check['metric'];missing=check['passed'] is None
        fields={'eps_latest':['eps'],'eps_avg':['eps'],'roe_avg':['roe_pct'],'yield_avg':['cash_yield_pct'],
            'revenue_cagr':['revenue'],'fcf_positive':['operating_cash_flow','capital_expenditure'],
            'fcf_coverage':['operating_cash_flow','capital_expenditure','cash_dividends_paid'],
            'dividend_streak':['cash_dividend_per_share']}.get(metric)
        years=[]
        if missing and fields:
            count=1 if metric=='eps_latest' else check['years']+1 if metric=='revenue_cagr' else check['years']
            for year in range(today.year-1,today.year-count-1,-1):
                row=rows.get(str(year),{})
                if metric=='dividend_streak':
                    absent=row.get('cash_dividend_per_share',row.get('cash_dividends_paid')) is None
                else:absent=any(row.get(field) is None for field in fields)
                if absent:years.append(year)
        state='available';reason='資料可計算；請核對來源及期間'
        if missing:
            if metric=='expense_pct':state='unsupported';reason='尚無自動核對年度總費用率的來源；管理費不可替代總費用率'
            elif metric in ('price_ma20','ma20_ma60','volatility'):
                state='history_missing';reason='行情過舊、歷史不足或價格調整事件；暫停此項判定'
            elif metric.startswith('eps') and symbol.endswith('.TWO'):
                state='verification_required';reason='上櫃多年EPS尚缺自動歷史來源；可補登年度財報，後續Q4快照將持續保存'
            elif metric=='etf_yield' and not tw:
                state='unsupported';reason='此ETF尚無可核對的完整發放日期來源'
            elif cooling:state='cooldown';reason='資料來源冷卻中，等待下次允許更新'
            elif not configured and not(metric.startswith('eps') and symbol.endswith('.TW')):
                state='not_configured';reason='伺服器尚未設定適用來源；本欄無法自動下載'
            elif queued:state='queued';reason='已安排背景補資料；來源仍可能不涵蓋完整期間'
            else:state='missing';reason='來源未涵蓋完整期間或仍待下載；不將缺漏當成0'
        labels.append({'metric':metric,'label':check['label'],'state':state,'reason':reason,
                       'missing_years':years,'required':check['required']})
    current=[]
    if data.get('kind')=='STOCK':
        for key,label in [('eps_ttm','EPS（TTM）'),('roe_ttm_pct','ROE（TTM）'),('paid_yield_pct','近365天已發配息率')]:
            detail=data.get('trailing_details',{}).get(key,{})
            if detail:
                state='available';reason=detail.get('basis','')
            elif key=='eps_ttm':
                state='verification_required';reason='缺少可核對股數基準的近一年EPS；年度EPS與單季相加均不替代，可於個人設定補登'
            elif key=='paid_yield_pct' and not tw and symbol!='AAPL':
                state='unsupported';reason='此美股尚未接入已發配息日期來源，增加下載次數無法補齊'
            elif cooling:state='cooldown';reason='來源冷卻中'
            elif not configured:state='not_configured';reason='伺服器尚未設定適用來源'
            else:state='missing';reason='仍缺完整期間、期初期末權益或完整發放日期；等待來源補齊'
            current.append({'metric':key,'label':label,'state':state,'reason':reason})
    return {'rule_fields':labels,'current_fields':current,
            'required_missing':sum(c['required'] and c['state']!='available' for c in labels)}
