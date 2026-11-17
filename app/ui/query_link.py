"""Consume a recommendation link once, without triggering network requests."""
import re


def apply_symbol_link(params, state):
    value = params.get('symbol')
    if not isinstance(value, str):
        return None
    value = value.strip().upper()
    if not re.fullmatch(r'\d{4}\.(TW|TWO)', value):
        return None
    if state.get('applied_symbol_link') != value:
        state['query_symbol'] = value
        state['applied_symbol_link'] = value
        # Never show another company's old result beneath the new selection.
        for key in ('result', 'download_result', 'download_symbol', 'download_notice_key'):
            state.pop(key, None)
        state['download_pending'] = False
    return value
