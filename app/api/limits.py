import asyncio
# 公開與個人查詢共用單一行情請求鎖。
quote_lock=asyncio.Semaphore(1)
