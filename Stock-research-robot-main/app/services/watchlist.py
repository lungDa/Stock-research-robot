from sqlalchemy import select,delete
from sqlalchemy.exc import IntegrityError
from app.db import Session,Watch,Preference
from app.providers.market import normalize

def watches(user):
    with Session() as s: return list(s.scalars(select(Watch.symbol).where(Watch.user==user).order_by(Watch.symbol)))
def add(user,symbol):
    symbol=normalize(symbol)
    if len(watches(user))>=30: raise ValueError('每人最多追蹤30檔')
    try:
        with Session.begin() as s: s.add(Watch(user=user,symbol=symbol))
    except IntegrityError: pass
    return symbol

def remove(user,symbol):
    with Session.begin() as s: s.execute(delete(Watch).where(Watch.user==user,Watch.symbol==normalize(symbol)))
def toggle(user,enabled):
    with Session.begin() as s: s.merge(Preference(user=user,enabled=enabled))
def subscribed():
    with Session() as s: return list(s.scalars(select(Preference.user).where(Preference.enabled.is_(True))))
