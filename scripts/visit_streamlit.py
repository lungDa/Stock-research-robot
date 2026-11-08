"""Best-effort public browser visit; never logs in or requests stock analysis."""
import os,re,time
from urllib.parse import urlsplit

def checked_url(value):
    p=urlsplit(value.strip())
    if p.scheme!='https' or not p.hostname or not p.hostname.endswith('.streamlit.app') or p.username or p.password or p.port not in (None,443) or p.query or p.fragment or p.path not in ('','/'):
        raise ValueError('Set repository variable PUBLIC_APP_URL to the HTTPS Streamlit homepage, without query parameters')
    return value.strip()

def visit(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        try:
            page=browser.new_page()
            page.set_default_timeout(5000)
            deadline=time.monotonic()+100
            page.goto(url,wait_until='domcontentloaded',timeout=30000)
            clicked=False
            while time.monotonic()<deadline:
                heading=page.get_by_role('heading',name=re.compile('股海燈塔'))
                if heading.count() and heading.first.is_visible():
                    # Allow the public Streamlit session to finish connecting.
                    page.wait_for_timeout(8000)
                    if heading.count() and heading.first.is_visible():
                        print('Confirmed public app heading rendered. This is not a continuous-availability guarantee.')
                        return
                wake=page.get_by_role('button',name=re.compile(r'Yes, get this app back up',re.I))
                if not clicked and wake.count() and wake.first.is_visible():
                    wake.first.click();clicked=True
                    print('Requested wake-up using the public sleeping-page button.')
                page.wait_for_timeout(1000)
            raise RuntimeError('Could not confirm app rendered within budget; manual wake-up may be required')
        finally:browser.close()

if __name__=='__main__':visit(checked_url(os.getenv('PUBLIC_APP_URL','')))
