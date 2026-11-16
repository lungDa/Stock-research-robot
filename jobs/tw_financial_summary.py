"""Allowlisted Chinese Actions summaries; never render raw provider/user text."""
import os
import re

from app.providers.source_errors import CONTRACTS


STAGES = {
    '官方目錄下載': '下載官方指標目錄', '官方目錄解析': '核對官方指標目錄',
    '官方目錄寫入': '儲存官方指標目錄', '公司快取讀取': '讀取公司快取',
    '公司代號下載': '查詢官方公司代號', '公司代號解析': '核對公司身分',
    '公司快取寫入': '儲存公司快取',
}
for field, label in (('eps', '每股盈餘 EPS'), ('roe_pct', '權益報酬率 ROE')):
    for suffix, action in (
        ('請求準備', '準備查詢'), ('下載', '下載'), ('解析', '核對'),
        ('快取讀取', '讀取既有資料'), ('資料整合', '整合資料'), ('寫入', '儲存資料'),
    ):
        STAGES['年度' + field + suffix] = '年度' + label + '：' + action

STATES = {
    'finished': '本批已結束', 'partial': '本批有失敗項目', 'failed': '本批失敗',
    'idle': '本批沒有符合條件的待更新標的', 'busy': '已有其他更新工作執行中',
    'limited': '已達本批請求、時間或來源配額限制', 'cooldown': '官方來源冷卻中',
}
GUIDANCE = {
    'timeout': ('連線或讀取逾時', '等待冷卻後由後續排程重試；若持續發生，檢查官方來源回應時間。'),
    'connection': ('網路、DNS 或 TLS 連線失敗', '檢查執行環境與官方來源的連線；不要反覆手動重跑。'),
    'json': ('回應不是有效的 JSON 資料', '可能是錯誤頁或回應格式改變；請維護者核對官方端點。'),
    'budget': ('回應超過大小或時間預算', '請維護者檢查回應大小與耗時；不要直接移除保護上限。'),
    'storage': ('資料庫操作失敗', '檢查資料庫連線與可用性；不要在公開紀錄貼出連線字串或密碼。'),
    'contract': ('資料未通過格式、公司身分或年度數值核對', '請維護者核對官方格式與解析規則；不要將缺漏補成 0 或放寬核對。'),
}


def _text(value):
    return value if isinstance(value, str) else ''


def _count(value):
    return str(value) if type(value) is int and 0 <= value <= 10**9 else '未提供'


def _diagnosis(detail):
    stage = _text(detail.get('stage'))
    code = _text(detail.get('error_code'))
    cause, action = GUIDANCE.get(code, ('尚無可辨識的錯誤分類', '請維護者檢查安全診斷；目前資訊不足以判定根因。'))
    if re.fullmatch(r'http_[1-5][0-9]{2}', code):
        status = int(code[5:])
        if status == 429:
            cause, action = '官方來源限制請求頻率（HTTP 429）', '等待來源冷卻解除；不要反覆重跑或繞過流量限制。'
        elif status in (401, 403):
            cause, action = f'官方來源拒絕存取（HTTP {status}）', '等待冷卻並檢查官方存取規則；這不代表需要新增付費 token。'
        elif status >= 500:
            cause, action = f'官方來源伺服器錯誤（HTTP {status}）', '等待後續排程重試；若持續發生，檢查官方服務狀態。'
        else:
            cause, action = f'官方來源回傳 HTTP {status}', '請維護者核對官方端點與請求格式。'
    elif code == 'contract' and stage in STAGES:
        # Only exact code-owned explanations may cross into public Markdown.
        reason = _text(detail.get('reason'))
        for safe_reason in CONTRACTS.values():
            if reason == stage + '：' + safe_reason:
                cause = safe_reason
                break
    return STAGES.get(stage, '階段未提供或無法辨識'), cause, action


def render_summary(entry):
    """Accept the parent's step envelope, including timeout/abnormal exits."""
    entry = entry if isinstance(entry, dict) else {}
    result = entry.get('result')
    lines = ['## 台股年度財務更新（EPS／ROE）', '']
    if entry.get('state') == 'timeout':
        lines += ['**結果：更新程序超過執行時間上限。**', '',
                  '尚未取得完整結果，不能據此判定官方來源逾時或資料寫入失敗。',
                  '建議：檢查各階段耗時與資料庫連線，再由後續排程續跑。']
    elif not isinstance(result, dict):
        lines += ['**結果：未取得可判讀的更新結果。**', '',
                  '可能是程序異常結束或結果格式不符，目前無法確認根因或更新筆數。',
                  '建議：請維護者檢查此步驟的安全診斷；不要貼出原始回應或密鑰。']
    else:
        state = _text(result.get('state'))
        lines += ['**結果：' + STATES.get(state, '狀態無法辨識') + '。**', '',
                  '| 官方請求次數 | 成功更新股票數 | 失敗項目數 |',
                  '| ---: | ---: | ---: |',
                  '| ' + ' | '.join(_count(result.get(k)) for k in
                    ('official_requests', 'updated_symbols', 'failed_feeds')) + ' |', '']
        if state == 'cooldown':
            lines += ['建議：等待既有冷卻解除，由後續排程再檢查；本次未重新連線，不能據此判定來源已恢復。', '']
        elif state in ('busy', 'limited'):
            lines += ['建議：等待目前工作結束或配額恢復，再由後續排程續跑；這不等於資料格式錯誤。', '']
        elif state == 'idle':
            lines += ['建議：若預期應有更新，檢查待處理佇列與標的設定；摘要不列出私人追蹤清單。', '']
        elif state == 'finished' and result.get('updated_symbols') == 0:
            lines += ['本批沒有新增資料；可能仍在準備目錄、等待個別項目冷卻，或已用完本批預算。', '']
        failures = result.get('failures')
        details = [d for d in failures[:4] if isinstance(d, dict)] if isinstance(failures, list) else []
        if details:
            lines += ['| 失敗階段 | 原因 | 建議處理方式 |', '| --- | --- | --- |']
            lines += ['| ' + ' | '.join(_diagnosis(d)) + ' |' for d in details]
            lines += ['', '最多顯示 4 筆診斷樣本；失敗項目數不等於失敗股票數。']
        elif state in ('partial', 'failed'):
            lines += ['尚無失敗階段與分類，不能只憑請求次數推斷根因。建議使用含安全診斷的版本取得下一次結果。']
    lines += ['', '本摘要僅說明本批執行情況；不代表全市場財務資料已補齊，也不驗證既有資料完整性。', '']
    return '\n'.join(lines)


def write_summary(entry):
    path = os.getenv('GITHUB_STEP_SUMMARY')
    if not path:
        return
    try:
        with open(path, 'a', encoding='utf-8') as output:
            output.write(render_summary(entry))
    except OSError:
        # Summary output must not change refresh results or expose the file path.
        print('台股財務摘要寫入失敗；更新結果不受影響。', flush=True)
