# V2.5 Render 管理員指定操作（開發分支）

1. 先確認指定帳號已使用 LINE Login 登入並完成平台八位數密碼設定，帳號狀態為啟用。
2. 由可信任管理者取得**自己的** LINE User ID（格式 U 加 32 位十六進位字元）；不要使用 LINE 顯示名稱或 LINE ID 暱稱。
3. Render → 對應 API 服務 → Environment → Add Environment Variable：
   - Key: `LIGHTHOUSE_BOOTSTRAP_ADMIN_LINE_USER_ID`
   - Value: 上述已驗證 LINE User ID
4. 儲存並重新部署**已包含此功能的版本**。啟動時，後端會檢查既有會員資料，且只在資料庫沒有管理員指定紀錄時建立唯一指定。
5. 登入後，以 Bearer session token 呼叫 `POST /admin/bootstrap/otp`。官方帳號向預先指定者傳送六位數 OTP。
6. 在五分鐘內以 Bearer session token 呼叫 `POST /admin/bootstrap/verify`，JSON: `{"code":"123456"}`（填收到的實際驗證碼）。成功後初始化完成。
7. 驗證後可移除 Render 預先指定變數；既有指定不會因移除而改變。

## 安全限制
- 如果已有不同指定帳號，服務啟動會拒絕覆寫；不得透過改環境變數移轉管理員。
- 不接受未完成個人密碼設定、未啟用的帳號。
- 不提供任何公開指定管理員 API。
- OTP 功能目前只有 API，尚無 Streamlit 表單；需使用已登入會話的授權 token 操作。
- 既有 `ADMIN_LINE_USER_IDS` 屬於舊版管理員機制，**本次沒有停用或遷移**；V2.5 權限使用 `current_lighthouse_admin`，不得誤以為舊端點已全面切換。
- **目前程式只提交至開發分支，未部署或驗收。**
