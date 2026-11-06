# 台股官方來源＋低流量更新包（2026-11-06）

## 更新步驟

1. 解壓縮壓縮檔，保留目錄結構。
2. 到 https://github.com/lungDa/Stock-research-robot 根目錄，Add file → Upload files。
3. 拖入 app、jobs、tests 三個資料夾，以及 streamlit_app.py 與本說明檔。這些資料夾只有本次變更的檔案，GitHub會新增/覆寫同路徑，不刪除其他檔案。
4. 檢查不要變成額外巢狀資料夾，例如 Taiwan-Official-Low-Traffic/app。應直接是 app/providers/taiwan_official.py 等。
5. Commit changes。等Render自動部署完成；未自動部署時 Manual Deploy → Deploy latest commit。
6. Streamlit應自動更新。必要時Reboot app，重新登入後按一次分析。
7. 先測試 2412、2330、0050；上櫃測試 6488.TWO、00679B.TWO。

無需新增API金鑰、修改資料庫、環境變數、main.py或requirements.txt。既有requirements已包含requests/pandas/lxml。
本次未更新遠端GitHub：先前連線建立分支與寫入均回403，因此需要使用者自行上傳。

## 來源與行為

- .TW → 臺灣證券交易所官方OpenAPI最新行情與個股月成交資訊。
- .TWO → 櫃買中心官方OpenAPI最新行情與個股月成交資訊。
- 商品名稱/ETF分類採證交所ISIN官方分類。分類失敗顯示UNKNOWN，不猜測。
- 台股不再呼叫Yahoo，包括基本資料。美股維持Yahoo及原有冷卻保護，本包沒有改善美股資料來源。
- 不需要付費行情服務或API金鑰，但所有官方端點仍可能維護、限流或阻擋雲端連線；本版沒有保證永不限流，也沒有代理輪換或驗證繞過。

## 降低流量

| 資料 | 共用/快取方式 |
|---|---|
| 全市場收盤快照 | 上市/上櫃各自共用1份，快取1小時 |
| 證券分類 | 每市場共用1份，快取24小時 |
| 本月個股日線 | 每檔每月份快取1小時 |
| 已結束月份日線 | 每檔每月份快取7天 |
| 個股官方分析結果 | 快取30分鐘 |
| 失敗請求 | 資料庫記錄5分鐘冷卻，避免每檔重打市場端點 |
| 同一程序同一來源host | 請求開始時間至少間隔3秒 |

快取使用既有PostgreSQL，Render與GitHub Actions必須仍使用同一DATABASE_URL。限速器本身為單程序，不是跨程序精準速率限制；資料庫快取/失敗紀錄可共用。

- 手動個股查詢、自選追蹤：最多回補最近4個月，並設本次時間預算；已快取月份不重新下載。
- 全市場輪掃：不逐檔下載歷史月份，只使用全市場快照和已有月快取。自選清單優先處理。
- 若只有單日資料，就顯示收盤價與日期，均線顯示缺資料，不報503。
- 歷史月份失敗時停止回補，保留快照/已取得資料；兩種都失敗又無舊快取時，仍會顯示行情暫不可用。
- 全市場波段名單只可能涵蓋已有足夠歷史的標的，不再用大量下載換取一次全市場完整日線。尚未回補的標的不會誤判為符合。

## 資料口徑與目前限制

1. 官方來源是盤後收盤資料，不是盤中即時報價，畫面保留資料實際日期。
2. 官方歷史價格未還原除權息，與原Yahoo還原技術價格不同，會顯示警示。偵測到超過30%跳動時，不自動判定波段符合；這不是完整的公司行動調整。
3. 月份不足或最新快照尚未補入完整日線時，波段缺項顯示缺資料，不跳過缺漏日硬算。
4. 本次未整合EPS、ROE、ETF費用率、實際現金配息歷史，不假造殖利率或由本益比反推EPS。價格查詢恢復不代表完整存股分析已完成。
5. 櫃買月成交仟股會乘1000換為股。全市場快照與月表統計範圍可能不同，不混用快照成交量計算量比。
6. 台股舊Yahoo分析快取在新查詢時會失效，改走官方來源；舊LINE快取需待該檔重新查詢/排程更新後才換新。
7. 字母尾碼ETF（例如00679B.TWO）已納入母體解析；純數字代號仍預設.TW，上櫃請明確輸入.TWO。

## 本包檔案

新增 app/providers/taiwan_official.py。
更新 app/providers/market.py、app/services/research.py、app/services/analysis.py、streamlit_app.py、jobs/scan.py、jobs/refresh_universe.py。
測試包括 tests/test_taiwan_official.py、tests/test_market_resilience.py、tests/test_universe.py。

## 驗證

- 42項離線pytest測試通過；涵蓋民國日期、上市/上櫃格式、仟股換算、共用快照只下載一次、失敗冷卻、單日資料保留、不明欄位拒絕、台股不呼叫Yahoo、全市場不下載個股歷史、拆併股跳動保護。
- Streamlit AppTest：官方單日行情、警示及缺資料提示可載入。
- compileall通過。
- 在本環境曾取得TWSE最新行情、2330歷史月表及6488櫃買月表HTTP 200；另有連線逾時/傳輸不完整，不能據此保證雲端穩定性。
- 新程式尚未在你的Render端完成端到端驗收。上傳部署後需實際重新查詢。

## 官方文件

https://openapi.twse.com.tw/
https://www.tpex.org.tw/openapi/
https://www.twse.com.tw/en/trading/historical/stock-day.html
https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code=3455&date=2023%2F10%2F01&id=&response=html
