import os, json
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()
@dataclass
class Settings:
    database_url: str = os.getenv('DATABASE_URL','sqlite:///./local.db')
    line_secret: str = os.getenv('LINE_CHANNEL_SECRET','')
    line_token: str = os.getenv('LINE_CHANNEL_ACCESS_TOKEN','')
    login_channel_id: str = os.getenv('LINE_LOGIN_CHANNEL_ID','')
    login_channel_secret: str = os.getenv('LINE_LOGIN_CHANNEL_SECRET','')
    login_callback: str = os.getenv('LINE_LOGIN_CALLBACK_URL','')
    public_app_url: str = os.getenv('PUBLIC_APP_URL','')
    api_public_url: str = os.getenv('API_PUBLIC_URL','')
    # 舊版 {存取金鑰: LINE userId} 身分對照；啟用LINE Login後停用網頁金鑰登入。
    users_json: str = os.getenv('USER_TOKENS_JSON','{}')
    @property
    def users(self):
        value=json.loads(self.users_json)
        if not isinstance(value,dict) or any(len(k)<24 or not isinstance(v,str) or not v.startswith('U') for k,v in value.items()):
            raise ValueError('USER_TOKENS_JSON 必須為 {至少24字元隨機金鑰: LINE userId}')
        return value
settings=Settings()
