"""One request per task. Oversized ranges split and resume instead of failing forever."""
import time
from app.providers.annual_free import FINMIND
from app.providers.bounded_http import ResourceLimitError
from app.providers.date_windows import split_window,replace_window


class SourceRejected(ValueError):
    def __init__(self,status):self.status=status;super().__init__('Source rejected request')


def batch(symbol,feed,state,today,download,compact,token):
    now=time.time()
    pending=list(state.get('pending_windows') or [{'start':f'{today.year-11}-01-01','end':str(today)}])
    window=pending[0]
    try:
        payload=download(FINMIND,{'dataset':feed,'data_id':symbol.split('.')[0],
            'start_date':window['start'],'end_date':window['end']},{'Authorization':'Bearer '+token})
    except ResourceLimitError:
        parts=split_window(window)
        return {**state,'status':'partial','pending_windows':parts+pending[1:],
                'coverage_windows':state.get('coverage_windows',[]),'last_attempt':now,
                'next_attempt':now+60,'last_error':'本批回應超過大小／時間預算，已拆分日期範圍等待續跑'},False
    if not isinstance(payload,dict):raise ValueError('Invalid source response')
    if payload.get('status')!=200:raise SourceRejected(payload.get('status'))
    raw=payload.get('data')
    if not isinstance(raw,list):raise ValueError('Invalid source data array')
    rows=compact(feed,raw,symbol.split('.')[0])
    if raw and not rows:raise ValueError('No usable matching source records')
    # A different symbol/date response cannot be treated as coverage of our window.
    if any(not window['start']<=str(row.get('date',''))<=window['end'] for row in rows):
        raise ValueError('Source date range mismatch')
    remaining=pending[1:]
    coverage=[w for w in state.get('coverage_windows',[]) if w.get('start')!=window['start'] or w.get('end')!=window['end']]
    coverage.append({**window,'at':now})
    records=replace_window(state.get('records',[]),rows,window)
    if not remaining and not records:raise ValueError('No source data; retain old snapshot')
    return {**state,'records':records,'pending_windows':remaining,'coverage_windows':coverage,
            'at':now,'last_attempt':now,'status':'partial' if remaining else 'ok',
            'next_attempt':now+(60 if remaining else 7*86400),'last_error':''},bool(records)
