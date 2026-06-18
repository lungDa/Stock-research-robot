import discord
from discord.ext import commands
import yfinance as yf
import asyncio
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import google.generativeai as genai
import sys
import random
import os
from fastapi import FastAPI, Response
import uvicorn

# ─── 1. 建立 FastAPI 網頁伺服器 ───
app = FastAPI()


@app.get("/")
async def home_get():
    return {"status": "🤖 股票駐守機器人 24H 暢通運作中！"}


@app.head("/")
async def home_head():
    # HEAD 請求不需要回傳內容
    return Response(status_code=200)


# =========================
# 🔑 設定
# =========================
# Render / Railway / Replit 等平台請設定環境變數：DISCORD_TOKEN
TOKEN = os.getenv("DISCORD_TOKEN")

MAX_WORKERS = 10
CONCURRENCY = 30
PORT = int(os.getenv("PORT", "10000"))

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


# =========================
# 🧠 快取（1分鐘）
# =========================
CACHE = {"data": None, "time": 0}


# =========================
# 🤖 Bot
# =========================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# =========================
# 📌 台股清單
# =========================
def get_all_tw_stocks():
    try:
        url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
        data = requests.get(url, timeout=10).json()
        return [d["公司代號"] for d in data if d.get("公司代號", "").isdigit()]
    except Exception as e:
        print(f"取得台股清單失敗：{e}")
        return ["2330", "2317", "2454", "2303", "2412"]


# =========================
# 🚀 批次抓資料
# =========================
def fetch_batch_data(codes):
    tickers = " ".join([f"{c}.TW" for c in codes])

    return yf.download(
        tickers,
        period="3mo",
        group_by="ticker",
        threads=True,
        progress=False,
        auto_adjust=False,
    )


# =========================
# ⚡ 快取控制
# =========================
def get_cached_data(codes):
    now = time.time()

    if CACHE["data"] is not None and now - CACHE["time"] < 60:
        return CACHE["data"]

    data = fetch_batch_data(codes)
    CACHE["data"] = data
    CACHE["time"] = now
    return data


# =========================
# ⚡ 粗篩
# =========================
def fast_filter(data):
    candidates = []

    try:
        codes = data.columns.levels[0]
    except Exception:
        return []

    for code in codes:
        try:
            df = data[code]
            close = df["Close"].dropna()

            if len(close) < 20:
                continue

            ma5 = close.tail(5).mean()
            ma20 = close.tail(20).mean()

            # 嚴格版：價格站上 MA5，MA5 站上 MA20，且 MA5 高於 MA20 至少 1%
            if close.iloc[-1] > ma5 > ma20 and ma5 > ma20 * 1.01:
                candidates.append(str(code).replace(".TW", ""))

        except Exception:
            continue

    return candidates


# =========================
# 📊 單檔資料工具
# =========================
def get_price(stock):
    try:
        hist = stock.history(period="5d", auto_adjust=False)
        if hist.empty:
            return None
        return float(hist["Close"].dropna().iloc[-1])
    except Exception as e:
        print(f"get_price error: {e}")
        return None


def get_eps(stock):
    try:
        info = stock.info
        return float(info.get("trailingEps") or 0)
    except Exception as e:
        print(f"get_eps error: {e}")
        return 0.0


def get_roe(stock):
    try:
        info = stock.info
        return float(info.get("returnOnEquity") or 0) * 100
    except Exception as e:
        print(f"get_roe error: {e}")
        return 0.0


def get_yield(stock, price):
    try:
        if not price:
            return 0.0

        div = stock.dividends
        if div.empty:
            return 0.0

        # 取最近 365 天現金股利總和
        recent_div = div[div.index >= div.index.max() - timedelta(days=365)]
        return float(recent_div.sum() / price * 100)
    except Exception as e:
        print(f"get_yield error: {e}")
        return 0.0


# =========================
# 🧠 精算
# =========================
def analyze_stock(code):
    try:
        stock = yf.Ticker(f"{code}.TW")

        hist = stock.history(period="3mo", auto_adjust=False)
        if hist.empty:
            return None

        close = hist["Close"].dropna()
        if len(close) < 20:
            return None

        price = float(close.iloc[-1])
        ma5 = close.tail(5).mean()
        ma20 = close.tail(20).mean()

        eps = get_eps(stock)
        roe = get_roe(stock)
        yld = get_yield(stock, price)

        # =========================
        # 🎯 嚴格條件整合
        # =========================
        if price > ma5 > ma20 and roe >= 20 and eps >= 3 and yld >= 5:
            level = "強力推薦購買"
            color = discord.Color.green()
        elif roe >= 15 and eps >= 2:
            level = "買"
            color = discord.Color.blue()
        else:
            level = "觀望"
            color = discord.Color.red()

        return {
            "code": code,
            "price": price,
            "eps": eps,
            "roe": roe,
            "yield": yld,
            "level": level,
            "color": color,
        }

    except Exception as e:
        print(f"error {code}: {e}")
        return None


# =========================
# 機器人回應測試指令
# =========================
@bot.command()
async def HIHI(ctx):
    await ctx.send("今天的龍大真帥，一定是很棒的一天!!")


# =========================
# 🚀 scan_fast
# =========================
@bot.command()
async def scan_fast(ctx):
    stocks = get_all_tw_stocks()
    msg = await ctx.send("🚀 掃描啟動...靜待5分鐘")

    # 批次資料
    batch_data = await asyncio.to_thread(get_cached_data, stocks)

    # 粗篩
    candidates = fast_filter(batch_data)

    total = len(candidates)
    completed = 0

    await msg.edit(content=f"⚡ 粗篩完成：{total} 檔")

    if total == 0:
        await ctx.send("⚠️ 粗篩沒有符合條件的股票")
        return

    semaphore = asyncio.Semaphore(CONCURRENCY)
    mention_list = []

    # =========================
    # 📊 進度更新
    # =========================
    async def progress():
        while completed < total:
            percent = (completed / total) * 100 if total else 100
            try:
                await msg.edit(content=f"🚀 掃描中 {completed}/{total}（{percent:.1f}%）")
            except Exception as e:
                print(f"進度訊息更新失敗：{e}")
            await asyncio.sleep(5)

    progress_task = asyncio.create_task(progress())

    # =========================
    # worker
    # =========================
    async def worker(code):
        nonlocal completed

        async with semaphore:
            try:
                data = await asyncio.to_thread(analyze_stock, code)
            except Exception as e:
                print(f"worker error {code}: {e}")
                data = None

            completed += 1

            if data and data["level"] == "強力推薦購買":
                return data

            return None

    tasks = [worker(code) for code in candidates]

    try:
       for coro in asyncio.as_completed(tasks):
        result = await coro
    
        if result:
    
            name = get_stock_name(result["code"])
    
            mention_list.append(
                f"{name} ({result['code']})"
            )
    
            embed = discord.Embed(
                title=f"🔥 強力推薦購買｜{name}",
                color=result["color"]
            )
                embed.add_field(name="價格", value=f"{result['price']:.1f}")
                embed.add_field(name="EPS", value=f"{result['eps']:.2f}")
                embed.add_field(name="ROE", value=f"{result['roe']:.1f}%")
                embed.add_field(name="殖利率", value=f"{result['yield']:.2f}%")

                await ctx.send(embed=embed)
    finally:
        progress_task.cancel()

    # =========================
    # 結果
    # =========================
    if mention_list:
        await ctx.send(
            f"🔥 強力推薦購買\n<@{ctx.author.id}>\n" + "\n".join(mention_list[:20])
        )
    else:
        await ctx.send("⚠️ 無強力推薦購買")


# =========================
# 📛 取得中文名稱
# =========================
def get_stock_name(code):

    code = str(code).replace(".TW", "")

    load_stock_names()

    if code in STOCK_NAME_CACHE:
        return STOCK_NAME_CACHE[code]

    try:
        info = yf.Ticker(f"{code}.TW").info

        return (
            info.get("shortName")
            or info.get("longName")
            or "未知名稱"
        )

    except:
        return "未知名稱"

    except Exception as e:
        print(f"TWSE 查中文名稱失敗：{e}")

    # 方法2：yfinance fallback
    try:
        info = yf.Ticker(code + ".TW").info
        return info.get("shortName") or info.get("longName") or "未知名稱"
    except Exception as e:
        print(f"yfinance 查中文名稱失敗：{e}")

    return "未知名稱"


# =========================
# 📊 分析
# =========================
@bot.command()
async def analyze(ctx, code):
    code = code.replace(".TW", "").strip()

    if not code.isdigit():
        await ctx.send("❌ 股票代號格式錯誤，例如：!analyze 2330")
        return

    full_code = code + ".TW"
    stock = yf.Ticker(full_code)

    price = await asyncio.to_thread(get_price, stock)
    if not price:
        await ctx.send("❌ 抓不到資料")
        return

    eps = await asyncio.to_thread(get_eps, stock)
    roe = await asyncio.to_thread(get_roe, stock)
    yld = await asyncio.to_thread(get_yield, stock, price)
    name = await asyncio.to_thread(get_stock_name, code)

    await ctx.send(
        f"📊 {name}（{full_code}）\n"
        f"價格 {price:.1f}\n"
        f"EPS {eps:.2f}\n"
        f"ROE {roe:.1f}%\n"
        f"殖利率 {yld:.2f}%"
    )


# =========================
# ▶️ 啟動
# =========================
@bot.event
async def on_ready():
    print(f"✅ 已登入：{bot.user}")


# ─── 3. 用同一個事件循環啟動 ───
async def main():
    if not TOKEN:
        raise RuntimeError(
            "找不到 DISCORD_TOKEN。請到部署平台的環境變數設定 DISCORD_TOKEN。"
        )

    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        server.serve(),
        bot.start(TOKEN),
    )


if __name__ == "__main__":
    asyncio.run(main())
