"""Stop scheduled/manual DB-writing workers while maintenance is enabled.

Exit nonzero on missing DB, malformed state or unavailable DB (fail closed).
"""
import sys
from app.db import get

def assert_writable():
    try:
        state=get('system:maintenance',{})
        if not isinstance(state,dict):
            raise ValueError('invalid maintenance state')
        if state.get('enabled') is True:
            raise RuntimeError('maintenance enabled')
    except Exception as exc:
        print(f'BLOCKED: database write job cannot start: {type(exc).__name__}',file=sys.stderr)
        raise SystemExit(75) from exc
    print('Maintenance guard: writes permitted')

if __name__=='__main__':
    assert_writable()
