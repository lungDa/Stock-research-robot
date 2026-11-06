import hmac
from fastapi import Header,HTTPException
from app.config import settings

def current_user(authorization:str=Header(default='')):
    token=authorization.removeprefix('Bearer ')
    if not authorization.startswith('Bearer '): raise HTTPException(401,'請先LINE登入並完成個人密碼驗證')
    if not settings.login_channel_id:
        for key,user in settings.users.items():
            if hmac.compare_digest(token,key): return user
    from app.api.line_login import digest
    from app.db import get
    from app.services.accounts import is_member
    import time
    session=get('auth:session:'+digest(token),{})
    member=get('member:'+session.get('user',''),{})
    if (session.get('expires',0)>time.time() and session.get('stage')=='active' and
        session.get('password_version')==member.get('password_version') and not member.get('password_change_required',True) and is_member(session.get('user',''))):return session['user']
    raise HTTPException(403,'登入已過期或無效，請重新使用LINE登入')
