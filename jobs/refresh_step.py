"""Run one refresh feed in isolation; emit a JSON result on the final line."""
import json
import sys

def run(name):
    from jobs.maintenance import run as clean
    from jobs.refresh_fundamentals import run as fundamentals
    from jobs.refresh_eps import run as eps
    from jobs.refresh_annual import run as annual
    from jobs.refresh_us_prices import run as prices
    from jobs.v26_market_coverage import run as coverage
    from jobs.refresh_paid_dividends import run as paid
    from jobs.refresh_tw_financials import run as tw_financials
    from jobs.refresh_history import run as history
    from jobs.refresh_tw_prices import run as tw_prices
    from jobs.refresh_universe import build as universe
    from jobs.refresh_cash_dividends import run as cash
    steps = {
        "maintenance": clean, "universe": universe, "tw_prices": tw_prices,
        "history": history, "fundamentals": fundamentals,
        "cash_dividends": cash, "tw_financials": tw_financials,
        "eps_first": eps, "eps_second": eps, "coverage_diagnostic": coverage,
        "annual": annual, "us_prices": prices, "paid": paid,
    }
    if name not in steps:
        raise ValueError("unknown refresh step")
    # Keep annual work below the parent process deadline.
    # The annual worker persists snapshots and its cursor after each attempt.
    if name == "annual":
        return annual(max_requests=2, seconds=18)
    return steps[name]()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m jobs.refresh_step STEP")
    value = run(sys.argv[1])
    print(json.dumps(value, ensure_ascii=False, default=str), flush=True)
