"""One bounded issuer dividend page per run. Explicit issuer allowlist only."""
import os,time,math
from datetime import datetime
from html.parser import HTMLParser
import requests
from app.db import init_db,get,put

SOURCES={'AAPL':'https://investor.apple.com/dividend-history/'}
class Table(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,text):
        if self.cell is not None:self.cell.append(text)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.row is not None and self.cell is not None:
            self.row.append(' '.join(' '.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None


def parse_apple(html):
    parser=Table();parser.feed(html)
    found=False;payments={};splits=[]
    for row in parser.rows:
        if row==['Declared','Record','Payable','Amount','Type']:found=True;continue
        if not found or len(row)!=5:continue
        raw=row[2].rstrip('*').strip();day=None
        for fmt in ('%B %d, %Y','%b %d, %Y'):
            try:day=datetime.strptime(raw,fmt).date().isoformat();break
            except ValueError:continue
        if not day:continue
        if 'Stock Split' in row[4]:splits.append(day);continue
        if row[4] not in ('Regular Cash','Special Cash'):continue
        try:value=float(row[3].replace('$','').replace(',',''))
        except ValueError:continue
        if not math.isfinite(value) or value<0:continue
        if day in payments and payments[day]!=value:raise ValueError('conflicting dividend rows')
        payments[day]=value
    if not payments:raise ValueError('No verified payment table')
    return {'payments':[{'date':d,'amount':v} for d,v in sorted(payments.items())],'splits':splits,'currency':'USD'}


def run():
    init_db();symbols=[s.strip().upper() for s in os.getenv('ANNUAL_SYMBOLS','').split(',')]
    from app.services.accounts import member_users
    from app.services.watchlist import watches
    symbols+= [s for user in member_users() for s in watches(user)]
    for symbol,url in SOURCES.items():
        if symbol not in symbols:continue
        now=time.time();key='paid:state:'+symbol
        if now<get(key,{}).get('next_attempt',0):continue
        put(key,{'next_attempt':now+86400})
        try:
            start=time.monotonic();chunks=[];size=0
            with requests.get(url,timeout=(2,2),stream=True,allow_redirects=False) as response:
                response.raise_for_status()
                if response.status_code!=200:raise ValueError('redirect or invalid response')
                for chunk in response.iter_content(8192):
                    size+=len(chunk)
                    if size>262144 or time.monotonic()-start>=6:raise ValueError('source exceeded budget')
                    chunks.append(chunk)
            data=parse_apple(b''.join(chunks).decode('utf-8-sig'))
            put('paid:shared:'+symbol,{**data,'source':url,'fetched_at':now})
            print({'paid_dividend_symbol':symbol,'records':len(data['payments'])})
        except Exception:print('配息日期來源未完成，保留舊資料：'+symbol)
        break  # one HTTP request total, no immediate retries


if __name__=='__main__':run()
