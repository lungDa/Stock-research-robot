"""Coverage accounting for an explicit market universe.

Coverage is measured against required fields only. Missing data is never
coerced to zero, and a partial universe must be labelled as partial.
"""
from collections import Counter

def summarize(universe, assessments):
    """Return coverage of unique symbols against per-symbol required checks.

    assessments maps symbol to a list of checks with required and passed keys.
    A symbol is evaluable only if it has at least one required check and every
    required check has a non-None outcome. A failed check is still evaluated.
    """
    symbols=list(dict.fromkeys(universe))
    missing=Counter()
    evaluable=0
    evaluated=0
    for symbol in symbols:
        checks=assessments.get(symbol)
        if not isinstance(checks,list):
            missing['not_assessed']+=1
            continue
        required=[c for c in checks if isinstance(c,dict) and c.get('required')]
        if not required:
            missing['no_required_checks']+=1
            continue
        evaluated+=1
        unknown=[c for c in required if c.get('passed') is None]
        if not unknown:
            evaluable+=1
        for check in unknown:
            missing[str(check.get('metric') or 'unknown')]+=1
    total=len(symbols)
    return {'universe_total':total,'assessed':evaluated,
            'evaluable':evaluable,'incomplete':total-evaluable,
            'coverage_pct':round(100*evaluable/total,2) if total else 0.0,
            'missing_by_metric':dict(sorted(missing.items())),
            'scope':'provided_universe_only',
            'disclaimer':'僅代表已納入本次母體的個股；未完成評估的股票不列入推薦。'}
