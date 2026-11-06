"""API 啟動入口。Streamlit 與排程使用各自入口。"""
import os
import uvicorn
if __name__ == '__main__':
    uvicorn.run('app.api.server:app', host='0.0.0.0', port=int(os.getenv('PORT','10000')))
