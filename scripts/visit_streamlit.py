"""Best-effort public browser visit; never logs in or requests stock analysis."""
import os,re,time
from urllib.parse import urlsplit

def checked_url(value):
    p=urlsplit(value.strip())
    if p.scheme!='https' or not p.hostname or not p.hostname.endswith('.streamlit.app') or p.username or p.password or p.port not in (None,443) or p.query or p.fragment or p.path not in ('','/'):
        raise ValueError('Set repository variable PUBLIC_APP_URL to the HTTPS Streamlit homepage, without query parameters')
    return value.strip()

def visible_in_frames(page,role,pattern):
    """Community Cloud embeds the live app in an iframe, not the outer page."""
    for frame in page.frames:
        if frame.parent_frame is not None:
            owner=frame.frame_element()
            if not owner.is_visible():
                continue
        matches=frame.get_by_role(role,name=re.compile(pattern,re.I))
        for index in range(matches.count()):
            candidate=matches.nth(index)
            if candidate.is_visible():
                return candidate
    return None

def diagnose(page):
    # Fixed labels/counts only: never print page text, cookies, or query tokens.
    print(f'Diagnostic: inspected {len(page.frames)} frame(s); app heading not confirmed.')
    for index,frame in enumerate(page.frames):
        headings=frame.get_by_role('heading',name=re.compile('股海燈塔'))
        print(f'Diagnostic: frame {index}, matching headings={headings.count()}')

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
                heading=visible_in_frames(page,'heading','股海燈塔')
                if heading is not None:
                    # Allow the public Streamlit session to finish connecting.
                    page.wait_for_timeout(8000)
                    if visible_in_frames(page,'heading','股海燈塔') is not None:
                        print('Confirmed public app heading rendered. This is not a continuous-availability guarantee.')
                        return
                wake=visible_in_frames(page,'button',r'Yes, get this app back up')
                if not clicked and wake is not None:
                    wake.click();clicked=True
                    print('Requested wake-up using the public sleeping-page button.')
                page.wait_for_timeout(1000)
            diagnose(page)
            raise RuntimeError('Could not confirm app rendered within budget; inspect frame diagnostics')
        finally:browser.close()

if __name__=='__main__':visit(checked_url(os.getenv('PUBLIC_APP_URL','')))
