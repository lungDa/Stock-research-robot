"""Refresh exchange calendars independently; failures never fabricate business days."""
from app.db import init_db
from app.services.freshness import local_now


def run():
    init_db()
    from app.services.market_recommendations import calendar
    calendar(local_now().year)
    return {'state':'finished','calendar_year':local_now().year}


if __name__ == '__main__':print(run())
