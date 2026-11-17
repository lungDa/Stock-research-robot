"""Deliver replies with safe failures and replay saved responses, not commands."""
import logging
import time

import requests

from app.channels import commands, line
from app.db import get, put, leased

log = logging.getLogger(__name__)
UNAVAILABLE = '服務暫時無法讀取資料，這次沒有執行指令。請稍後再試；若持續無回覆，請聯絡管理者。'
COMMAND_FAILED = '這次處理未能完成，無法確認操作結果。若剛才是追蹤或通知設定，請稍後先查「我的清單」或「通知設定」，再決定是否重試。'
MAINTENANCE = '股海燈塔維護中，這次沒有執行查詢或變更設定。請稍後再試，無須連續重傳。'
TIMEOUT = '這次處理逾時，無法確認操作結果。請稍後先查「我的清單」或「通知設定」確認變更；查詢資料可稍後重試。'


def report(stage, exc):
    # Do not log exceptions, tokens, event IDs, user IDs or message contents.
    status = getattr(getattr(exc, 'response', None), 'status_code', None)
    category = ('timeout' if isinstance(exc, (TimeoutError, requests.Timeout)) else
                'connection' if isinstance(exc, requests.ConnectionError) else
                'http_' + str(status) if type(status) is int and 400 <= status <= 599 else 'internal')
    log.warning('LINE delivery stage=%s category=%s', stage, category)


def supported(event):
    if not isinstance(event, dict):
        return False
    source, message = event.get('source'), event.get('message')
    return (isinstance(source, dict) and source.get('type') == 'user'
            and isinstance(source.get('userId'), str) and bool(source['userId'])
            and isinstance(event.get('replyToken'), str) and bool(event['replyToken'])
            and isinstance(event.get('webhookEventId'), str) and bool(event['webhookEventId'])
            and (event.get('type') == 'follow' or
                 event.get('type') == 'message' and isinstance(message, dict)
                 and message.get('type') == 'text' and isinstance(message.get('text'), str)))


def notify_unavailable(events, message):
    """No database or commands: safe even when maintenance blocks all writes."""
    failed = False
    for event in events:
        if not supported(event):
            continue
        try:
            line.reply(event['replyToken'], message)
        except Exception as exc:
            report('unavailable_reply', exc)
            failed = True
    return not failed


def deliver(events):
    failed = False
    for event in events:
        if not supported(event):
            continue
        stage = 'event_storage'
        started = False
        sent = False
        try:
            key = 'event:' + event['webhookEventId']
            with leased('line:' + key, 180) as owned:
                if not owned:
                    failed = True
                    continue
                state = get(key, {})
                if state.get('status') == 'done':
                    continue
                # A reply failure must not repeat notification/watchlist changes.
                response = state.get('response')
                if response is None:
                    # If a prior worker stopped during a command, its side effects
                    # are unknown. Report that fact rather than executing it twice.
                    response = COMMAND_FAILED
                    if state.get('status') != 'processing':
                        put(key, {'status': 'processing', 'at': time.time()})
                        started = True
                        stage = 'command'
                        try:
                            response = commands.respond(event['source']['userId'],
                                '開始使用' if event['type'] == 'follow' else event['message']['text'])
                        except Exception as exc:
                            report(stage, exc)
                            response = TIMEOUT if isinstance(exc, (TimeoutError, requests.Timeout)) else COMMAND_FAILED
                    stage = 'response_storage'
                    put(key, {'status': 'pending', 'at': time.time(), 'response': response})
                stage = 'reply'
                line.reply(event['replyToken'], response)
                sent = True
                stage = 'completion_storage'
                put(key, {'status': 'done', 'at': time.time()})
        except Exception as exc:
            report(stage, exc)
            failed = True
            if stage in ('event_storage', 'response_storage') and not sent:
                notify_unavailable([event], COMMAND_FAILED if started or stage == 'response_storage' else UNAVAILABLE)
    return not failed
