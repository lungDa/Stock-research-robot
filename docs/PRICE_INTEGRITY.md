# 台股行情有效性與最新價格基準還原

## 行情日核對

台股查詢、LINE、掃描與評分使用同一判定。讀取已保存的交易日曆，不在行情有效性判斷時連外下載：

- 18:17 台灣時間前，以前一交易日為應有盤後行情；18:17 起，以當日或最近開市日為準。
- 13:30 後若來源已有可核對的當日收盤，允許提前採用當日資料；盤中不接受當日資料冒充已完成日線。
- 週末及長假回溯實際開市日，不因超過七天就把長假前最後收盤當成過期，也不把漏一個交易日的舊價當成最新。
- 缺交易日曆、跨年缺上一年度日曆、未取得應有收盤日、停牌或日期異常時，保留實際資料並阻擋買入分級。臨時休市依 `recommendations:session_overrides` 的日期布林值覆寫；未確認休市不猜測。
- 原始行情日、下載時間不改寫。美股維持原有有效性規則，本次只變更台股。

## 免費公司行動資料與計算

不使用需付費權限的 `TaiwanStockPriceAdj`，使用既有 `FINMIND_TOKEN` 免費可查的事件來源：

| 事件 | 資料集 | 事件前／後參考欄位 |
| --- | --- | --- |
| 除權息 | TaiwanStockDividendResult | before_price / after_price |
| 分割、反分割 | TaiwanStockSplitPrice | before_price / after_price |
| 變更面額 | TaiwanStockParValueChange | before_close / after_ref_close |
| 減資恢復交易 | TaiwanStockCapitalReductionReferencePrice | ClosingPriceonTheLastTradingDay / PostReductionReferencePrice |

每筆係數為「事件後參考價 ÷ 事件前收盤價」，只乘到事件前的歷史收盤價；多事件累乘，以本段最新收盤日為基準，最新收盤價保持原值。
例如 100 元分割後參考價 25 元，事件前價格乘 0.25。現金除息同理，不用實際除息日成交價推算係數。

原始 `price`、`history[].close` 及成交量均保留。`adjusted_history` 是另存的還原序列，`ma20`、`ma60` 與波動率改用此序列；`technical_basis=latest_price_adjusted`，`adjustment_status=verified` 才可採用台股均線因子。網頁同時顯示原始及還原圖，LINE 顯示還原資料是否核對。

四種事件資料須涵蓋整段日線；即使回傳空陣列，也必須是成功取得該期間的結果。事件日期及事件前收盤須與日線核對。遇公司不符、負值、非有限值、同日衝突、日線缺口或未解釋的巨大跳動，均線／波動率留白。相同事件不重複套用；不拿宣告股利或當日價格跳空猜調整係數。近期有公司行動時，成交量比先保留缺值，避免股數變動造成量比誤判。

## 部署與續補

程式合併並部署後，在 GitHub Actions 執行 **Replenish data and clean expired records** 一次，確認 `market_metadata` 已取得當年度日曆。既有每日四次排程也會接續執行，不另發 LINE 訊息。

日曆改用證交所年度報表端點 `https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule`，以 `date=YYYY0101&response=json` 指定西元年度。不能用會提早切換到下一年度的 OpenAPI 最新表，也不能以 `queryYear` 參數取代 `date`。下載結果必須核對 `date`、`queryYear`、民國年度標題、欄位、總筆數及每列日期；不符或不完整時不覆寫既有快取。

`market_metadata` 各年度獨立處理：當年與前一年是必要資料，十一月起另預載下一年。必要年度任一失敗回報 `partial`；下一年尚未公告不影響當年續補，但在 `years` 結果保留失敗原因。前一年也能從空資料庫重新下載，元旦及跨年長假不依賴部署前留下的快取。每年度快取六小時；舊 OpenAPI 快取會由新來源重新核對。交易日依資料列的「名稱」判斷，最後交易日的「說明」提到其他日期無交易，不會將該列日期誤列為休市。臨時休市仍依已核對的日期覆寫，不從年度例假表推測颱風休市。

新增 `corporate_actions` 步驟，每次最多兩次來源請求，與其他工作共用原有 FinMind 每日 100 次預算。追蹤、查詢待補及 `ANNUAL_SYMBOLS` 列入任務，另逐檔輪替市場母體。每檔四來源可跨批次完成；缺 Token、額度不足或來源失敗時保留既有涵蓋區間，不冒稱本次下載成功。

首次上線不代表已補齊全市場。四來源尚未完整涵蓋的標的，會顯示還原資料未齊、均線缺資料；這可能使符合數暫時減少。跨年應保留先前年度的日曆快取。服務仍是免費日線研究工具，不是即時報價或完整回測資料庫。

## 驗證範圍

測試使用合成事件驗證除息、分割／反分割、變更面額、減資、多事件累乘、衝突、日曆長假／跨年，以及查詢與排名的均線一致性。未操作正式資料庫或驗收全市場資料完整率。

來源規格：

- [FinMind 基本面資料集與欄位](https://finmind.github.io/tutor/TaiwanMarket/Fundamental/)
- [FinMind 免費／付費方案範圍](https://finmind.github.io/Pricing/)
- [TWSE 除權除息計算結果](https://www.twse.com.tw/zh/announcement/ex-right/twt49u.html)
- [TWSE 市場開休市日期](https://www.twse.com.tw/zh/trading/holiday.html)
- [TWSE 2026 年度報表 JSON](https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?date=20260101&response=json)
