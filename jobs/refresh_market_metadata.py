"""Refresh exchange calendars independently; failures never fabricate business days."""
from app.db import init_db
from app.services.freshness import local_now


def run():
    init_db()
    from app.services.market_recommendations import calendar
    now=local_now()
    required=[now.year,now.year-1]
    optional=[now.year+1] if now.month>=11 else []
    results={}
    for year in required+optional:
        try:
            row=calendar(year)
            results[str(year)]={'state':'finished','source_date':row['source_date']}
        except Exception as exc:
            # Continue to other years. A rejected download never overwrites a
            # verified cache and never turns an unknown year into weekdays.
            results[str(year)]={'state':'failed','reason':str(exc)[:200],
                                'error':type(exc).__name__}
    return {'state':'finished' if all(results[str(y)]['state']=='finished' for y in required) else 'partial',
            'calendar_year':now.year,'required_years':required,'optional_years':optional,
            'years':results}


if __name__ == '__main__':print(run())
