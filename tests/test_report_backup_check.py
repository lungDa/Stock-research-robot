import importlib.util
from pathlib import Path
from unittest.mock import Mock
import pytest
spec=importlib.util.spec_from_file_location('report_probe',Path(__file__).parents[1]/'scripts/check_tw_report_backup.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

def reports():
    r={'id':42,'symbol':'2330.TW','exchange':'twse','stock_code':'2330','stock_name':'台積電','report_period':'2025-12-31','doc_type':'annual'}
    return {'items':[r]}, {**r,'content':'基本每股盈餘／本期淨利／權益總額；此為測試文字'}

def test_two_bounded_calls_and_no_numeric_inference():
    f=Mock(side_effect=reports());result=p.probe('2330.TW','fake-secret',f)
    assert f.call_count==2 and not result['numeric_values_verified']
    assert result['markers']['eps_labels'] and 'content' not in result
    assert f.call_args_list[0].kwargs['max_bytes']==65536
    assert f.call_args_list[1].kwargs['max_bytes']==524288
    assert all(call.kwargs['seconds']==6 for call in f.call_args_list)

def test_invalid_symbol_no_network():
    f=Mock()
    with pytest.raises(ValueError):p.probe('AAPL','key',f)
    f.assert_not_called()

def test_identity_mismatch_does_not_fetch_report():
    meta,doc=reports();meta['items'][0]['symbol']='2412.TW';f=Mock(return_value=meta)
    with pytest.raises(ValueError):p.probe('2330.TW','key',f)
    assert f.call_count==1

def test_text_must_match_metadata_period():
    meta,doc=reports();doc['report_period']='2024-12-31'
    with pytest.raises(ValueError):p.probe('2330.TW','key',Mock(side_effect=[meta,doc]))

def test_main_does_not_expose_key_in_remote_exception(monkeypatch,capsys):
    monkeypatch.setenv('DATASINK_API_KEY','private-key')
    monkeypatch.setattr(p,'probe',Mock(side_effect=RuntimeError('https://example.com/?apikey=private-key')))
    with pytest.raises(SystemExit):p.main()
    assert 'private-key' not in capsys.readouterr().out
