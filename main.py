import discord
from discord.ext import commands
import yfinance as yf
import asyncio
import time
import nest_asyncio
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import google.generativeai as genai
from google.colab import userdata
import sys
import random
import os
from fastapi import FastAPI
import uvicorn

# ─── 1. 建立 FastAPI 網頁伺服器 ───
app = FastAPI()

# 瀏覽器用的 GET 請求
@app.get("/")
async def home_get():
    return {"status": "🤖 誰是臥底機器人 24 暢通運作中！"}

# 專門給 UptimeRobot 用的 HEAD 請求（完全不帶 request 參數，避免底層解析出錯）
@app.head("/")
async def home_head():
    return None  # HEAD 請求依照 HTTP 規範本來就不需要回傳內容，給個空值即可

# =========================
# 🔑 設定
# =========================
TOKEN = userdata.get("DISCODE_TOKEN")
MAX_WORKERS = 10
CONCURRENCY = 30

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# 讀取金鑰: api_keys 是一個變數,不要加引號
api_keys = userdata.get('GEMINI_KEY')
genai.configure(api_key=api_keys)

# 初始化時就定義好它是誰
ai_persona = "你是一個intj的雙魚座工程師,叫作小夫。請稱呼使用者為『BOSS』。"
model = genai.GenerativeModel(
model_name='gemini-3.1-flash-lite-preview',
system_instruction=ai_persona
)

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
        return [d["公司代號"] for d in data if d["公司代號"].isdigit()]
    except:
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
        progress=False
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
    except:
        return []

    for code in codes:
        try:
            df = data[code]
            close = df["Close"].dropna()

            if len(close) < 20:
                continue

            ma5 = close.tail(5).mean()
            ma20 = close.tail(20).mean()

            # 👉 嚴格版（多加趨勢確認）
            if close.iloc[-1] > ma5 > ma20 and ma5 > ma20 * 1.01:
                candidates.append(code.replace(".TW", ""))

        except:
            continue

    return candidates

# =========================
# 🧠 精算
# =========================
def analyze_stock(code):
    try:
        stock = yf.Ticker(f"{code}.TW")

        hist = stock.history(period="3mo")
        if hist.empty:
            return None

        price = float(hist["Close"].iloc[-1])

        ma5 = hist["Close"].tail(5).mean()
        ma20 = hist["Close"].tail(20).mean()

        info = stock.info

        eps = info.get("trailingEps") or 0
        roe = (info.get("returnOnEquity") or 0) * 100

        div = stock.dividends
        yld = (div.last("365D").sum() / price * 100) if price else 0

        # =========================
        # 🎯 嚴格條件整合
        # =========================
        if (
            price > ma5 > ma20 and
            roe >= 20 and
            eps >= 3 and
            yld >= 5
        ):
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
            "color": color
        }

    except Exception as e:
        print(f"error {code}: {e}")
        return None
# =========================
# 機器人回應 測試 指令
# =========================
@bot.command()

async def HIHI(ctx):

  await ctx.send('今天的龍大真帥,一定是很棒的一天!!')

@bot.command()
async def say(ctx):
    chat = model.start_chat(history=[])
    while True:
      response = chat.send_message("請你在心中默想一個故事,讓我來玩海龜湯")
      await ctx.send(f"小夫:{response.text}")

# =========================
# 🚀 scan_fast
# =========================
@bot.command()
async def scan_fast(ctx):

    stocks = get_all_tw_stocks()
    msg = await ctx.send("🚀 掃描啟動...靜待5分鐘")

    # 批次資料
    batch_data = get_cached_data(stocks)

    # 粗篩
    candidates = fast_filter(batch_data)

    total = len(candidates)
    completed = 0

    await msg.edit(content=f"⚡ 粗篩完成：{total} 檔")

    semaphore = asyncio.Semaphore(CONCURRENCY)
    mention_list = []

    # =========================
    # 📊 進度更新
    # =========================
    async def progress():
        while completed < total:
            percent = (completed / total) * 100 if total else 100
            await msg.edit(
                content=f"🚀 掃描中 {completed}/{total}（{percent:.1f}%）"
            )
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
            except:
                data = None

            completed += 1

            if data and data["level"] == "強力推薦購買":
                return data

            return None

    tasks = [worker(code) for code in candidates]

    for coro in asyncio.as_completed(tasks):
        result = await coro

        if result:
            mention_list.append(result["code"])

            embed = discord.Embed(
                title=f"🔥 強力推薦購買｜{result['code']}",
                color=result["color"]
            )

            embed.add_field(name="價格", value=f"{result['price']:.1f}")
            embed.add_field(name="EPS", value=f"{result['eps']:.2f}")
            embed.add_field(name="ROE", value=f"{result['roe']:.1f}%")
            embed.add_field(name="殖利率", value=f"{result['yield']:.2f}%")

            await ctx.send(embed=embed)

    progress_task.cancel()

    # =========================
    # 結果
    # =========================
    if mention_list:
        await ctx.send(
            f"🔥 強力推薦購買\n<@{ctx.author.id}>\n" +
            "\n".join(mention_list[:20])
        )
    else:
        await ctx.send("⚠️ 無強力推薦購買")

# =========================
# 📛 取得中文名稱
# =========================
def get_stock_name(code):
    code = code.replace(".TW", "")

    # 方法1：TWSE API（最穩）
    try:
        url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
        data = requests.get(url, timeout=5).json()

        for d in data:
            if d["公司代號"] == code:
                return d["公司簡稱"]

    except:
        pass

    # 方法2：yfinance fallback
    try:
        info = yf.Ticker(code + ".TW").info
        return info.get("shortName") or info.get("longName")
    except:
        pass

    return "未知名稱"


# =========================
# 📊 分析
# =========================
@bot.command()
async def analyze(ctx, code):

    code = code.replace(".TW", "")
    full_code = code + ".TW"

    stock = yf.Ticker(full_code)

    price = get_price(stock)
    if not price:
        await ctx.send("❌ 抓不到資料")
        return

    eps = get_eps(stock)
    roe = get_roe(stock)
    yld = get_yield(stock, price)

    # 👉 新增：中文名稱
    name = get_stock_name(code)

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

nest_asyncio.apply()
bot.run(TOKEN)
