# 股海燈塔：美股行情共用快取修正

## 為什麼AAPL仍顯示503

SEC更新的是年度財報；原本股價與日線仍由Render向Yahoo查詢。這次錯誤為YFRateLimitError，因此財報下載成功仍可能看不到行情。

## 這版修改

1. 在既有手動年度更新及每日工作中，增加FinMind USStockPrice日線下載。
2. 直接使用既有GitHub Secret FINMIND_TOKEN，不需把Token複製到Render或Streamlit。
3. Render／LINE優先讀取共用日線快取，不必每次連Yahoo。快取在72小時內且行情日距今天不超過7天才可作為有效來源；仍顯示真正的交易日期，並非即時報價。
4. 沒有有效FinMind快取時，保留既有Yahoo流程及舊行情備援。
5. Yahoo失敗又沒有可用舊行情，但已有共用年度財報時，回傳「僅年度財報」。價格與日期留空，不補零；網頁可繼續看年度數值。LINE會說明目前僅有財報。
6. 技術指標只接受來源完整的Adj_Close，缺還原價時不以未還原價冒充。圖表及收盤價仍為來源Close。
7. 股票／ETF分類沿用既有明確分類；有SEC公司10-K資料時才可補公司分類。不從股票代號猜ETF。資料集未涵蓋或分類不明時，保留缺資料。

## 安裝與驗證

此更新包依賴先前已安裝的免費年度基本面更新包，請保留現有其他檔案。

1. 將包內app、jobs、tests、.github/workflows及streamlit_app.py依原路徑上傳main，覆蓋同名檔案。注意.github開頭有點。
2. 確認GitHub Actions的Secret FINMIND_TOKEN仍在；ANNUAL_SYMBOLS Variable仍含AAPL，例如2330.TW,AAPL。
3. 等Render與Streamlit更新部署。
4. Actions → Refresh free annual data → Run workflow。這次會多出「Refresh shared US daily prices (two symbols)」步驟。
5. 展開新步驟，確認us_price_updated至少1，表示至少一檔日線快取已寫入；綠色工作結束本身不等於有資料。
6. 回Streamlit查AAPL、按分析，核對來源為「FinMind / USStockPrice」與實際行情日期。
7. 若新步驟顯示未完成，把不含Token的步驟紀錄提供檢查；不要反覆重跑。資料集涵蓋、帳號權限與免費用量仍可能造成失敗。

同一個FinMind來源若前面的年度下載已遇到限流，本步驟也會遵守來源冷卻，可能顯示0次請求。請等冷卻結束；不以切換IP或不斷重試繞過限制。

## 請求與時間預算

- 每次美股日線工作最多2檔、2次請求；每檔最多256KiB，6秒串流軟預算，工作流程步驟硬限制1分鐘。
- 每檔一天最多一次嘗試；空資料、解析錯誤或失敗時保留舊快取。
- FinMind非成功狀態及HTTP401/403/429會共用整個來源的一天冷卻。
- 與年度工作合計，單次執行最多8次年度請求＋2次日線請求；不擴大原本年度下載上限。
- 日期以來源交易日為準。週末可能仍顯示星期五；顯示下載時間並不代表當日有交易。
- 更新股票沿用成員追蹤清單及ANNUAL_SYMBOLS，不主動掃全部美股。
- 無需新金鑰；不發LINE推播，不變更你的通知同意或個人設定。

## 驗證範圍

本機自動測試驗證解析、還原價缺漏、錯誤資料排除、共用快取跳過Yahoo、僅財報備援、請求上限與冷卻。尚未使用你的FinMind Token在正式環境驗證日線下載。

FinMind官方USStockPrice說明：https://finmind.github.io/tutor/UnitedStatesMarket/Technical/
