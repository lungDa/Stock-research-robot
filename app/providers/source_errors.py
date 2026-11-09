"""Safe diagnostic categories. Never persist raw exception text or response bodies."""
import json
import requests
from app.providers.bounded_http import ResourceLimitError

CONTRACTS={
 'Cash-flow catalog mismatch':'無法核對官方現金流量表目錄',
 'Cash-flow report period mismatch':'官方回應的年度／季別與請求不符',
 'Not a cash-flow statement':'官方回應不是現金流量表',
 'Cash-flow unit mismatch':'現金流量表幣別／金額單位未通過核對',
 'Ambiguous cash-flow company columns':'現金流量表公司欄位重複，無法唯一對應',
 'Invalid cash-flow number':'現金股利支出數字格式未通過核對',
 'Cash-flow table limit':'現金流量表超過大小或表格處理預算',
 'Official catalog contract changed':'官方目錄的指標名稱／單位無法辨識',
 'Invalid company lookup':'公司查詢回應格式不符',
 'Company identity missing or ambiguous':'公司查詢沒有唯一符合的股票代號',
 'Annual unit mismatch':'年度數值單位不符',
 'Not cumulative Q4':'回應不是第4季累計全年口徑',
 'Invalid annual periods':'年度座標格式不符',
 'Expected full-year Q4 cumulative periods':'年度座標不是完整Q4期間',
 'Company series does not match verified identity':'數值序列的公司識別不符',
 'Company identity metadata mismatch':'公司代號與回應中繼資料不符',
 'Company code cannot be bound to this series':'數值序列無法綁定已核對的公司代號',
 'No usable completed annual periods':'回應沒有可使用的完整年度數值',
 'No unambiguous full-year EPS table':'PDF沒有可辨識的完整年度EPS表',
 'Company identity mismatch':'PDF股票代號不符',
 'Missing report date':'PDF缺少唯一產製日期',
 'Stale or future report':'PDF產製日期過舊或在未來',
 'Invalid PDF':'回應不是允許的PDF',
}

def describe(exc,stage):
    status=getattr(exc,'status',None) or getattr(getattr(exc,'response',None),'status_code',None)
    try:status=int(status)
    except (TypeError,ValueError):status=None
    if status is not None and not 100<=status<=599:status=None
    if isinstance(exc,requests.Timeout):code='timeout';reason='連線或讀取逾時'
    elif isinstance(exc,requests.ConnectionError):code='connection';reason='網路／DNS／TLS連線失敗'
    elif status:code='http_'+str(int(status));reason='來源HTTP狀態 '+str(int(status))
    elif isinstance(exc,json.JSONDecodeError):code='json';reason='來源未回傳有效JSON，可能回傳HTML錯誤頁'
    elif isinstance(exc,ResourceLimitError):code='budget';reason='回應超過本批大小或時間預算'
    else:code='contract';reason=CONTRACTS.get(str(exc),'回應未通過格式或數值核對')
    return {'error_code':code,'stage':stage,'reason':stage+'：'+reason}
