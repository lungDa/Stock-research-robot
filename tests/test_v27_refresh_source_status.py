"""Regression checks for partial source failures and bounded coverage."""
import subprocess
from contextlib import contextmanager
from unittest.mock import patch
from jobs import refresh_data

@contextmanager
def owned(*args, **kwargs):
    yield True

def test_fundamentals_feed_error_marks_partial():
    def fake_run(cmd, **kwargs):
        if cmd[-1] == 'fundamentals':
            output = '[{"market":"TWO","status":"failed:ValueError"}]'
        else:
            output = '{"state":"cached"}'
        return subprocess.CompletedProcess(cmd, 0, stdout=output + '\n', stderr='')
    with patch.object(refresh_data, 'STEPS', ['fundamentals', 'eps_first']), \
         patch.object(refresh_data, 'init_db'), patch.object(refresh_data, 'put'), \
         patch.object(refresh_data, 'leased', owned), \
         patch.object(refresh_data.subprocess, 'run', side_effect=fake_run):
        result = refresh_data.run()
    assert result['steps']['fundamentals']['state'] == 'partial'
    assert result['steps']['eps_first']['state'] == 'finished'
    assert result['state'] == 'partial'
