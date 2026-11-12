"""Read-only persisted Neon snapshot access for the V2.6 dashboard.

Never infer verified six-factor completeness from the older three-field diagnostic.
"""
import time
from fastapi import APIRouter, Depends
from app.api.security import current_user
from app.db import get

router = APIRouter(prefix='/coverage', tags=['coverage'])
MAX_AGE = 48 * 3600


@router.get('/summary')
def summary(user=Depends(current_user)):
    diagnostic = get('v26:coverage:diagnostic', {}) or {}
    universe = get('v26:universe:audit', {}) or {}
    verified = get('v26:universe:verified_symbols', {}) or {}
    now = time.time()
    diagnostic_fresh = isinstance(diagnostic.get('at'), (int, float)) and 0 <= now - diagnostic['at'] <= MAX_AGE
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
        'three_field_diagnostic': {
            'fresh': diagnostic_fresh,
            'stock_count': diagnostic.get('market_symbols') if diagnostic_fresh else None,
            'known_fields': diagnostic.get('known_fields') if diagnostic_fresh else None,
            'expected_fields': diagnostic.get('expected_fields') if diagnostic_fresh else None,
            'coverage_ratio': diagnostic.get('partial_coverage_ratio') if diagnostic_fresh else None,
            'updated_at': diagnostic.get('at') if diagnostic_fresh else None,
        },
        'note': 'Neon目前只有三欄診斷快照；六項財務指標的來源與年度尚未逐項核對，不顯示全市場六項完整率。',
    }
