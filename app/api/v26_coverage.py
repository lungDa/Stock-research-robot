"""Read-only persisted Neon snapshot access for the V2.6 dashboard.

Never infer verified six-factor completeness from the older three-field diagnostic.
"""
import time
from fastapi import APIRouter, Depends, HTTPException
from app.api.security import current_user
from app.db import get

router = APIRouter(prefix='/coverage', tags=['coverage'])
MAX_AGE = 48 * 3600


@router.get('/summary')
def summary(user=Depends(current_user)):
    diagnostic = get('v26:coverage:diagnostic', {}) or {}
    six = get('v27:coverage:six_factor_provisional', {}) or {}
    universe = get('v26:universe:audit', {}) or {}
    verified = get('v26:universe:verified_symbols', {}) or {}
    now = time.time()
    diagnostic_fresh = isinstance(diagnostic.get('at'), (int, float)) and 0 <= now - diagnostic['at'] <= MAX_AGE
    six_fresh = isinstance(six.get('at'), (int, float)) and 0 <= now - six['at'] <= MAX_AGE
    universe_fresh = isinstance(universe.get('at'), (int, float)) and 0 <= now - universe['at'] <= MAX_AGE
    universe_verified = bool(universe_fresh and universe.get('verified') is True
                             and verified.get('verified') is True
                             and verified.get('at') == universe.get('at'))
    return {
        'source': 'NEON_DOCUMENTS',
        'six_factor_verified': False,
        'six_factor_coverage': None,
        'scheduler_gate_eligible': False,
        'universe': {
            'verified': universe_verified,
            'counts': universe.get('market_counts') if universe_fresh else None,
            'issue_count': universe.get('issues_count') if universe_fresh else None,
            'updated_at': universe.get('at') if universe_fresh else None,
        },
        'six_factor_provisional': {
            'fresh': six_fresh, 'stock_count': six.get('stock_count') if six_fresh else None,
            'known_items': six.get('known_items') if six_fresh else None,
            'expected_items': six.get('expected_items') if six_fresh else None,
            'coverage_ratio': six.get('coverage_ratio') if six_fresh else None,
            'missing_by_factor': six.get('missing_by_factor') if six_fresh else None,
            'market_complete': six.get('market_complete') if six_fresh else None,
            'verified': False,
        },
        'three_field_diagnostic': {
            'fresh': diagnostic_fresh,
            'stock_count': diagnostic.get('market_symbols') if diagnostic_fresh else None,
            'known_fields': diagnostic.get('known_fields') if diagnostic_fresh else None,
            'expected_fields': diagnostic.get('expected_fields') if diagnostic_fresh else None,
            'coverage_ratio': diagnostic.get('partial_coverage_ratio') if diagnostic_fresh else None,
            'updated_at': diagnostic.get('at') if diagnostic_fresh else None,
        },
        'note': '六項指標僅提供既有資料的初步缺漏診斷，尚未通過來源與期間交叉核對；不得用於95%排程切換。',
    }

@router.get('/stock/{symbol}')
def stock(symbol: str, user=Depends(current_user)):
    from app.providers.market import normalize
    from app.services.v26_coverage_adapter import read_stock
    try:
        return read_stock(normalize(symbol))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
