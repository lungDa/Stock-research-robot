"""手動工作流程：發布預設圖文選單，不發送推播；同版本重跑不重複建立。"""
import argparse,hashlib,json,time
from pathlib import Path
import requests
from app.config import settings

IMAGE=Path(__file__).resolve().parents[1]/'assets'/'line-richmenu.png'
COMMANDS=['功能選單','查詢','我的清單','今日重點','個人設定','綁定']

def definition():
    edges=[0,833,1666,2500]
    return {'size':{'width':2500,'height':1686},'selected':True,
        'name':'lighthouse-assistant-v1','chatBarText':'股海燈塔功能選單',
        'areas':[{'bounds':{'x':edges[i%3],'y':(i//3)*843,'width':edges[i%3+1]-edges[i%3],'height':843},
                  'action':{'type':'message','text':cmd}} for i,cmd in enumerate(COMMANDS)]}

def api(method,url,**kwargs):
    headers={'Authorization':'Bearer '+settings.line_token,**kwargs.pop('headers',{})}
    with requests.request(method,url,headers=headers,timeout=(2,4),stream=True,allow_redirects=False,**kwargs) as r:
        r.raise_for_status();raw=b'';start=time.monotonic()
        for chunk in r.iter_content(4096):
            raw+=chunk
            if len(raw)>131072 or time.monotonic()-start>6:raise RuntimeError('選單回應超過預算')
        return json.loads(raw) if raw else {}

def publish():
    if not settings.line_token:raise RuntimeError('請設定GitHub Secret LINE_CHANNEL_ACCESS_TOKEN')
    image=IMAGE.read_bytes()
    if len(image)>1048576:raise ValueError('選單圖片超過1MiB')
    payload=definition()
    version=hashlib.sha256(image+json.dumps(payload,sort_keys=True).encode()).hexdigest()[:12]
    payload['name']='lighthouse-assistant-'+version
    base='https://api.line.me/v2/bot'
    existing=api('GET',base+'/richmenu/list').get('richmenus',[])
    menu_id=next((r['richMenuId'] for r in existing if r.get('name')==payload['name']),None)
    if not menu_id:menu_id=api('POST',base+'/richmenu',json=payload)['richMenuId']
    # 即使上一次在上傳圖片時失敗，同版本仍能接續。
    api('POST','https://api-data.line.me/v2/bot/richmenu/'+menu_id+'/content',data=image,headers={'Content-Type':'image/png'})
    api('POST',base+'/user/all/richmenu/'+menu_id)
    print('預設圖文選單已發布；未發送推播。舊選單未刪除。')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--dry-run',action='store_true');args=parser.parse_args()
    if args.dry_run:print(json.dumps(definition(),ensure_ascii=False));print('image_bytes',IMAGE.stat().st_size)
    else:publish()
