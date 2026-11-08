# 股海燈塔：免費歷年基本面更新包

此包新增免費年度資料下載與評分串接，並非保證所有台股、美股、ETF都能補齊十年資料。缺漏仍依使用者選擇的缺資料規則處理，不把缺資料補成零或視為符合。

## 1. 註冊 FinMind（免費）

官網：https://finmindtrade.com/
依官網操作註冊、驗證Email、登入，至會員資料頁複製API Token。不要將Token放進程式、CSV、公開Variable或對話截圖。

GitHub lungDa/Stock-research-robot → Settings → Secrets and variables → Actions → Secrets → New repository secret：
- Name：FINMIND_TOKEN
- Secret：貼上剛取得的Token。

免費資料集有資料覆蓋、授權及用量限制；本程式不使用付費全市場查詢，也不自動開通付費服務。

## 2. 設定美股 SEC 來源（免API金鑰）

在同一個GitHub Secrets頁面新增：
- Name：SEC_USER_AGENT
- Secret：以「專案名稱＋你願意提供給SEC的維護聯絡Email」組成，例如 StockLighthouse 你的Email。

此值作為HTTP User-Agent送給SEC識別自動請求，不是LINE Email驗證或API密碼。若未含Email，程式不發SEC請求。不要填虛構聯絡資料。

## 3. 上傳與選擇要補資料的股票

將更新包的 app、jobs、.github/workflows、tests 與 streamlit_app.py 按原路徑覆蓋／新增到GitHub main；.github開頭有點，不要改為github。
本包沿用現有其他專案檔案，不需刪除資料庫或重新建立帳號。

程式自動處理所有成員的追蹤清單。也可新增 Actions → Variables → Repository variable：
- Name：ANNUAL_SYMBOLS
- Value：2330.TW,AAPL,0050.TW,VOO

這是公開股票代號，不是Secret。請使用逗號分隔；上櫃要明寫.TWO。第一次測試建議先填2330.TW,AAPL，避免一開始加入太多檔使輪替變慢。

現有DATABASE_URL、USER_TOKENS_JSON等Secrets照舊；Token只需放GitHub，Render與Streamlit讀共用資料庫，不需另存FinMind Token。

確認Render和Streamlit已部署這次程式後，Actions → Refresh free annual data → Run workflow。
這是獨立手動工作，不發LINE訊息。之後既有Daily scan and digest也會在掃描前執行一批。

## 4. 怎麼驗證

- 展開Refresh bounded annual batch：觀察annual_requests、updated_symbols、failed_feeds。
- 工作顯示綠色只代表批次有正常結束；updated_symbols=0或failed_feeds>0不代表下載成功。
- 回到Streamlit重新分析該代號，展開「歷年基本面與來源」，查看新增年度、幣別、期間、來源及共用年度更新時間。
- 追蹤多檔時需多次排程才逐步補齊；每個來源成功後七天內共用快取，重跑會跳過已完成項目，不會無限重抓。
- 失敗項目保留舊資料並等一天後再試；FINMIND_TOKEN／SEC_USER_AGENT未設定時不請求對應來源。
- 既有公開行情快取可繼續使用，但要重新按分析取得最新評分回應；不用刪快取或資料庫。

## 5. 本版實際涵蓋

| 類別 | 自動補入的內容 | 仍可能缺漏／限制 |
| --- | --- | --- |
| 台股個股 | 四季完整時合計營收與稅後淨利、年末累計營業現金流、可辨識的取得不動產廠房設備現金支出、平均期初期末權益ROE、依發放日整理現金股利、年末價格推算年度殖利率 | FinMind單季EPS股數基準可能不同，本版不相加。年度EPS僅沿用官方Q4快照或個人年度CSV；股利支出只接受可辨識的實付現金流科目。無法保證所有公司的ROE、FCF及股利覆蓋資料齊全 |
| 美股個股 | SEC US-GAAP／USD的10-K、10-K/A：年度稀釋EPS、淨利、權益、營業現金流、資本支出、已支付普通股股利、營收；由一致年度期間推算ROE | 僅標準科目，外國公司20-F、IFRS與自訂科目尚不支援；缺科目不以其他項目冒充。宣告每股股利只展示，不當已付股利，因此美股多年每股現金殖利率仍可能缺資料 |
| 台股ETF | 沿用獨立ETF評分；FinMind有涵蓋的配息，依已到發放日整理近365日每股現金配息，再除以查詢價格 | 不套公司EPS、ROE、FCF；資料集未涵蓋時留白。年度總費用率沒有新增可靠自動來源 |
| 美股ETF | 沿用Yahoo現有日線、近一年現金配息、動能與波動；有足夠歷史時標示近365日配息口徑 | Yahoo仍可能限流，沒有新增Yahoo重試。SEC公司10-K下載不適用ETF；年度總費用率仍需可靠來源，不把管理費或不明費率冒充總費用率 |

- 年度現金殖利率：每個曆年已到發放日的現金股利／該年未還原年底收盤價；五年規則再取各年平均。非目前價格倒推五年，亦非未來殖利率保證。
- 台股ROE採總稅後淨利／平均期初期末總權益；與其他網站的母公司ROE定義可能不同。
- SEC以實際會計年度開始、結束日期配對，不相加重複揭露或將季度當年度；同期間優先用較新申報值。
- EPS門檻以報表幣別每股計：台股TWD、美股USD。沒有自動匯率換算，請在個人規則設定核對門檻。
- 年度規則仍依既有方式，以去年為終點；SEC會計年度以結束年標示，不把今年尚未結束的曆年資料湊成全年。
- 十年配息只接受逐年已到發放日的每股現金股利，或直接揭露的已支付普通股現金股利總額；沒有資料的年度不推定為零。
- 任何一個必要欄位缺漏，採「封鎖」模式時仍顯示資料不足。個人CSV優先於共用自動資料，不會覆蓋別人的匯入。

## 6. 流量與資料預算

- 不在評分、LINE或網頁新增財報下載；只讀共用快取。既有行情查詢仍保留原本來源流程。
- 單次工作最多8次HTTP請求（含SEC股票代號對照表），每份最多1MiB，串流軟預算6秒。
- 約48秒後不再啟動新請求；來源步驟有2分鐘工作流程硬限制。
- 每項成功後7天冷卻；失敗保留舊快照並冷卻1天。FinMind API非成功、或HTTP401/403/429會對整個來源冷卻一天，避免對多檔重複打被限流來源。
- 股票／資料集的輪替位置持久保存，可手動再次執行繼續下一批。初次補齊需要時間，不代表即時全市場涵蓋。
- SEC下載單一concept，不下載可能過大的完整companyfacts；若仍超過大小預算，該項保留缺資料。
- 工作只記錄代號、資料集及計數，不輸出Token、請求Header或包含金鑰的網址。

## 驗證範圍

133項本機自動測試已通過（含15項新增年度資料測試），檢查年度口徑、季度與年度區分、重複股利、現金流累計、SEC重編與幣別、個人匯入優先、ETF獨立評分、請求數上限與來源冷卻。
尚未使用你的FinMind Token與正式GitHub runner做端到端資料驗證，不能把程式測試通過當作所有標的資料完整。

官方文件：
- https://finmind.github.io/tutor/TaiwanMarket/Fundamental/
- https://finmind.github.io/quickstart/
- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
