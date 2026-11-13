from app.services.coverage_summary import summarize


def test_unknown_is_missing_but_failed_is_evaluable():
    checks={
        'A':[{'metric':'eps','required':True,'passed':False}],
        'B':[{'metric':'eps','required':True,'passed':None},
             {'metric':'fcf','required':True,'passed':None}],
        'C':[{'metric':'eps','required':False,'passed':None}],
    }
    result=summarize(['A','B','C','D','A'],checks)
    assert result['universe_total']==4
    assert result['assessed']==2
    assert result['evaluable']==1
    assert result['coverage_pct']==25.0
    assert result['missing_by_metric']=={
        'eps':1,'fcf':1,'no_required_checks':1,'not_assessed':1}


def test_empty_universe_and_missing_assessments():
    assert summarize([],{})['coverage_pct']==0.0
    result=summarize(['2330.TW'],{})
    assert result['evaluable']==0
    assert result['missing_by_metric']['not_assessed']==1
