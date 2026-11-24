"""串流讀取及大小預算；只保留完整JSON紀錄，不把截斷JSON當成完整市場。"""
import codecs
import json
import time
import requests

class ResourceLimitError(RuntimeError):
    pass


def _extract(buffer, decoder, records, state):
    while True:
        buffer = buffer.lstrip()
        if not buffer:
            return buffer, state
        if state == 'closed':
            raise ValueError('市場JSON陣列後有額外內容')
        if buffer.startswith(']'):
            if state == 'item':
                raise ValueError('市場JSON陣列末尾有多餘逗號')
            state = 'closed'
            buffer = buffer[1:]
            continue
        if state == 'separator':
            if not buffer.startswith(','):
                raise ValueError('市場JSON紀錄缺少分隔逗號')
            state = 'item'
            buffer = buffer[1:]
            continue
        if not buffer.startswith('{'):
            raise ValueError('市場資料必須為JSON物件陣列')
        try:
            item, end = decoder.raw_decode(buffer)
        except json.JSONDecodeError:
            return buffer, state
        records.append(item)
        buffer = buffer[end:]
        state = 'separator'


def fetch_json(url, params=None, *, max_bytes=131072, seconds=6, array=False, headers=None, socket_timeout=(2,2)):
    started = time.monotonic()
    decoder = codecs.getincrementaldecoder('utf-8-sig')()
    json_decoder = json.JSONDecoder()
    buffer = ''
    records = []
    opened = False
    array_state = 'first'
    consumed = 0
    reason = ''
    try:
        with requests.get(url, params=params, headers=headers, timeout=socket_timeout, stream=True, allow_redirects=False) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ResourceLimitError('官方端點未直接回傳資料')
            if not array and int(response.headers.get('Content-Length', '0') or 0) > max_bytes:
                raise ResourceLimitError('回應超過大小預算，停止下載')
            for chunk in response.iter_content(8192):
                if time.monotonic() - started >= seconds:
                    reason = '時間預算'; break
                if not chunk:
                    continue
                remaining = max_bytes - consumed
                allowed = chunk[:max(0, remaining)]
                consumed += len(allowed)
                buffer += decoder.decode(allowed)
                if array:
                    if not opened:
                        buffer = buffer.lstrip()
                        if buffer:
                            if not buffer.startswith('['):
                                raise ValueError('市場來源未回傳JSON陣列')
                            opened = True; buffer = buffer[1:]
                    if opened:
                        buffer, array_state = _extract(buffer, json_decoder, records, array_state)
                if len(chunk) > remaining:
                    reason = '大小預算'; break
    except requests.RequestException:
        if not array or not records:
            raise
        reason = '連線中斷'
    if not reason:
        buffer += decoder.decode(b'', final=True)
    if array:
        complete = array_state == 'closed' and not reason
        if not records:
            raise ResourceLimitError('沒有取得完整市場紀錄')
        return {'records': records, 'complete': complete, 'reason': reason or ('回應未完整結束' if not complete else '')}
    if reason:
        raise ResourceLimitError(f'回應超過{reason}，停止下載')
    return json.loads(buffer)

