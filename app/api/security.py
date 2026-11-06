import hmac
from fastapi import Header,HTTPException
from app.config import settings

def current_user(authorization:str=Header(default='')):
    token=authorization.removeprefix('Bearer ')
    if not authorization.startswith('Bearer '): raise HTTPException(401,'需要個人存取金鑰')
    for key,user in settings.users.items():
        if hmac.compare_digest(token,key): return user
    raise HTTPException(403,'金鑰無效')
