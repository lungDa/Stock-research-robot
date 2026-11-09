"""Bounded date partitions and coverage checks, without guessing missing rows."""
from datetime import date,timedelta


def split_window(window):
    start=date.fromisoformat(window['start']);end=date.fromisoformat(window['end'])
    if (end-start).days<31:raise ValueError('Minimum source window reached')
    middle=start+(end-start)//2
    # Recent periods first: current metrics can recover before old history.
    return [{'start':str(middle+timedelta(days=1)),'end':str(end)},
            {'start':str(start),'end':str(middle)}]


def covers(windows,start,end,*,now=None,max_age=None):
    cursor=date.fromisoformat(str(start));end=date.fromisoformat(str(end))
    eligible=[]
    for window in windows:
        try:
            if max_age is not None and not 0<=now-window.get('at',0)<=max_age:continue
            a=date.fromisoformat(window['start']);b=date.fromisoformat(window['end'])
        except (KeyError,ValueError,TypeError):continue
        eligible.append((a,b))
    for a,b in sorted(eligible):
        if b<cursor:continue
        if a>cursor:return False
        cursor=max(cursor,b+timedelta(days=1))
        if cursor>end:return True
    return False


def replace_window(old,new,window):
    """Replace this authoritative interval; retain other intervals and conflicts."""
    start,end=window['start'],window['end']
    return [row for row in old if not start<=str(row.get('date',''))<=end]+list(new)
