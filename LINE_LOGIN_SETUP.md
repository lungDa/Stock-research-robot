# 股海燈塔：公開瀏覽＋LINE個人帳戶

本包是累積覆蓋更新，含上一版多因子設定、單檔升降級通知、A1基本面及18:17盤後排程。尚未提交GitHub、未部署，沒有真實密碼、Channel secret、資料庫或個人年度資料。

## 使用流程
- 開啟網站即可看行情與預設規則的市場批次選股，不要求金鑰。
- 個人功能：左側LINE登入 → LINE確認自己的身分 → 首次輸入0000 → 必須改成剛好8位半形數字 → 設定個人清單、評分與通知。
- 預設0000只限初次使用。新密碼可以保留開頭0；不接受英文字母、全形數字或非8位長度。
- 每個LINE身分獨立帳戶，不以姓名或共用密碼選帳戶。密碼加鹽scrypt雜湊保存。
- 再次登入：LINE認證後輸入自己的8位密碼。LINE的密碼由LINE處理，股海燈塔個人密碼由本服務處理，兩者不同。
- 首次密碼未修改前，個人API無法存取；新綁定使用者的個人LINE指令、通知與掃描也先暫停。既有未遷移LINE身分維持相容。
- 個人密碼修改後，其他工作階段失效。登出撤銷目前工作階段。網站不在瀏覽器永久保存密碼；重新整理/關閉頁面可能需要再登入。

## 一、LINE Developers設定（必須新增LINE Login Channel）
1. 開啟 https://developers.line.biz/console/ ，選擇現有Messaging API機器人所在Provider（目前截圖為「龍大」）。不要另外新建Provider。
2. 新增Channel，類型選LINE Login，應用程式選Web app，名稱可用「股海燈塔登入」。現有Messaging API Channel繼續保留，不能拿它的ID/Secret直接代替LINE Login。
3. 在LINE Login設定加入回呼網址，完整照抄：
   https://stock-research-robot.onrender.com/auth/line/callback
4. 在此Login Channel的Linked LINE Official Account設定，連結「股海燈塔」官方帳號。通知需要使用者先加入該官方帳號為好友；網頁登入不代表必定已加好友。
5. 複製這個新LINE Login Channel的Channel ID與Channel secret，僅放到Render環境變數，不要寫入GitHub或傳到聊天。
6. 開發模式先由有權限的測試LINE帳號驗證；要開放親友使用時，依LINE Console要求完成發布與必要設定。

官方說明：
https://developers.line.biz/en/docs/line-login/getting-started/
https://developers.line.biz/en/docs/line-login/integrate-line-login/
https://developers.line.biz/en/docs/messaging-api/getting-user-ids/

同Provider可取得相同LINE userId，原有追蹤與設定用userId保存，因此可沿用。若新建在不同Provider，會被視為不同身分，原資料無法自動對上。

## 二、Render新增5個環境變數
| 名稱 | 值 |
| --- | --- |
| LINE_LOGIN_CHANNEL_ID | 新LINE Login Channel的ID |
| LINE_LOGIN_CHANNEL_SECRET | 新LINE Login Channel的Secret |
| LINE_LOGIN_CALLBACK_URL | https://stock-research-robot.onrender.com/auth/line/callback |
| API_PUBLIC_URL | https://stock-research-robot.onrender.com |
| PUBLIC_APP_URL | 複製目前Streamlit完整HTTPS首頁網址，不含查詢參數 |

原有DATABASE_URL、Messaging API的LINE_CHANNEL_ACCESS_TOKEN及LINE_CHANNEL_SECRET維持。Streamlit原API_BASE_URL維持指向Render，無須新增個人密碼Secret。先前提出的共用密碼方案已取消，不使用SHARED_ACCESS_PASSWORD。
USER_TOKENS_JSON可保留既有身分對照；設定LINE_LOGIN_CHANNEL_ID後，舊長金鑰不再作為網頁個人登入方法。排程仍會讀取既有身分以及已完成初始密碼修改的新LINE帳戶。
五個變數尚未設好時，公開頁面照常可用，個人LINE登入會明確顯示尚未設定。

## 三、部署與驗證
1. 將本包內程式依原路徑上傳/覆蓋GitHub，包含.github。保留現有Secret，不上傳.env。
2. Render加上五個變數後部署最新版本；Streamlit等候同步更新。
3. 用無痕視窗開網站，應看得到行情/市場選股；個人清單及設定不能使用，不會要求長金鑰。
4. 左側使用LINE登入，在LINE授權後返回網站；第一次應要求0000，再要求8位數字新密碼。改密碼前不能讀寫個人功能。
5. 用自己帳號加入2330並修改評分設定；換另一個LINE帳號登入，清單/設定應獨立，初始密碼也各自是0000。
6. 在個人設定頁可再修改密碼；另一個已登入工作階段應失效。
7. 確認已將股海燈塔官方帳號加好友，再開啟個人升降級通知。沒有分級變化時不推播為正常結果；維持原單檔通知與每日上限。

## 流量與資料限制
公開查詢優先讀取快取；無快取時全站每分鐘最多2次、每天最多20次外部行情更新。快取較舊會保留實際日期並標示。公開與個人共用一把行情請求鎖；公開模式不載入個人年度匯入、清單或自訂設定。
多因子歷史財務資料仍未自動補齊5～10年；不足時顯示資料不足，可用上一版的個人年度CSV匯入。ETF年度總費用與完整近一年已發配息仍待資料接入，不補造。
LINE登入使用state、原瀏覽器HttpOnly/Secure cookie、nonce與PKCE，伺服器驗證ID token。一次性交接碼60秒有效，不把個人密碼或長效session放進網址；一般session12小時，初始驗證階段10分鐘。OAuth流程須在同一瀏覽器完成，不要跨瀏覽器複製回呼連結。

驗證：97項測試通過，含公開/個人隔離、回呼cookie/state/nonce/PKCE、一次性交接、初始0000、強制8位數字、不同人獨立密碼與資料、改密碼/登出失效、公開更新限額。Streamlit訪客畫面及密碼驗證→強制修改→個人設定互動通過。LINE真實登入仍需新增Channel及部署後端到端驗證，尚未使用正式帳號測試。
