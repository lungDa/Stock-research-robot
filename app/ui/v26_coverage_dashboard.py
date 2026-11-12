"""Read-only V2.6.2 coverage dashboard.

Uses the existing authenticated quote API for an on-demand single stock.
No synthetic market totals and no client-side admin mutation.
"""
import pandas as pd
import streamlit as st

FIELDS = {
    'eps': 'EPS（五年）',
    'roe_pct': 'ROE（五年）',
    'fcf': '自由現金流（五年）',
    'revenue_cagr': '營收 CAGR',
    'cash_yield_pct': '現金殖利率（五年）',
    'cash_dividend_years': '現金配息紀錄（十年）',
}


def render(api, personal, is_admin):
    st.subheader('📊 財務資料完整率')
    if not personal:
        st.info('請先完成 LINE 登入及個人密碼驗證，才能查看此頁面。')
        return

    st.caption('V2.6.2 介面預覽｜正式全市場完整率尚未接入 Neon；不以示範數字冒充真實統計。')
    a, b, c = st.columns(3)
    a.metric('上市普通股完整率', '待連線')
    b.metric('上櫃普通股完整率', '待連線')
    c.metric('全市場回補進度', '待連線')
    st.info('全市場母體核對、完整率彙總與回補工作狀態尚未提供經驗證的 API，因此暫不顯示百分比。')

    with st.form('v26_coverage_lookup'):
        symbol = st.text_input('個股代號（僅供既有資料查詢）', value='2330')
        lookup = st.form_submit_button('查看既有財報資料')
    if lookup:
        st.session_state.v26_coverage_symbol = symbol.strip().upper()
    target = st.session_state.get('v26_coverage_symbol')
    if target:
        # This endpoint is already protected by the application's session token.
        result = api('GET', '/quote/' + target)
        if result:
            if result.get('kind') != 'STOCK' or not str(result.get('symbol', '')).endswith(('.TW', '.TWO')):
                st.warning('此頁僅顯示台灣上市、上櫃個股；不將 ETF 或其他商品列入普通股完整率。')
            else:
                st.write('個股：', result.get('name', ''), '｜', result.get('symbol', target))
                annual = result.get('annual_rows') or {}
                rows = []
                for year, item in sorted(annual.items(), reverse=True):
                    if not isinstance(item, dict):
                        continue
                    rows.append({
                        '年度': year,
                        'EPS': item.get('eps'),
                        'ROE（%）': item.get('roe_pct'),
                        '營業現金流': item.get('operating_cash_flow'),
                        '資本支出': item.get('capital_expenditure'),
                        '現金股利支出總額': item.get('cash_dividends_paid'),
                        '營收': item.get('revenue'),
                        '現金殖利率（%）': item.get('cash_yield_pct'),
                    })
                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                    st.caption('此表為既有年度資料的原值預覽。尚未完成逐年度來源、口徑及期間核對，不據此宣稱六項指標已完整。空白不等於零。')
                else:
                    st.warning('目前沒有可顯示的年度財報資料，待後續資料回補。')
                quality = result.get('data_quality') or {}
                fields = quality.get('rule_fields') or []
                if fields:
                    st.markdown('#### 既有資料缺漏原因')
                    st.dataframe(pd.DataFrame([{
                        '項目': item.get('label'),
                        '狀態': item.get('state'),
                        '缺漏年度': '、'.join(map(str, item.get('missing_years') or [])),
                        '說明': item.get('reason'),
                    } for item in fields]), use_container_width=True, hide_index=True)

    st.divider()
    if is_admin:
        st.caption('管理員模式：手動回補功能尚未接入經後端授權的管理 API，暫不開放操作。')
    else:
        st.caption('一般使用者：僅供查看，不提供全市場回補操作。')
