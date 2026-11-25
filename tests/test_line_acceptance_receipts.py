from unittest.mock import Mock
import pytest
import requests
from app.channels import line
from app.db import get
from jobs import recommend

@pytest.mark.parametrize('status,headers',[(200,{'x-line-request-id':'request'}),(409,{'x-line-accepted-request-id':'accepted'})])
def test_line_acceptance_receipt(monkeypatch,status,headers):
    monkeypatch.setattr(line,'settings',Mock(line_token='test'))
    response=Mock(status_code=status,headers=headers)
    monkeypatch.setattr(line.requests,'post',Mock(return_value=response))
    receipt=line.push('user','message','retry')
    assert receipt['http_status']==status
    assert receipt['delivery_status']=='api_accepted_only'
    assert receipt['request_id']==headers.get('x-line-request-id')

def test_unverified_conflict_not_accepted(monkeypatch):
    monkeypatch.setattr(line,'settings',Mock(line_token='test'))
    response=Mock(status_code=409,headers={})
    response.raise_for_status.side_effect=requests.HTTPError()
    monkeypatch.setattr(line.requests,'post',Mock(return_value=response))
    with pytest.raises(requests.HTTPError):
        line.push('user','message','retry')

def test_receipt_saved_without_resending(monkeypatch):
    receipt={'http_status':200,'request_id':'request','delivery_status':'api_accepted_only'}
    push=Mock(return_value=receipt)
    monkeypatch.setattr(recommend,'push',push)
    recommend.deliver('user','receipt-test',['hello'],False,100)
    recommend.deliver('user','receipt-test',['hello'],False,100)
    assert get('receipt-test')['messages'][0]['acceptance']==receipt
    push.assert_called_once()
