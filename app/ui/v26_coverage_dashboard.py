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
    summary = api('GET', '/coverage/summary')
    if summary:
        universe = summary.get('universe') or {}
        diagnostic = summary.get('three_field_diagnostic') or {}
        counts = universe.get('counts') or {}
        if universe.get('verified'):
            a.metric('上市普通股數量（已核對）', counts.get('TW', '待核對'))
            b.metric('上櫃普通股數量（已核對）', counts.get('TWO', '待核對'))
        if diagnostic.get('fresh') and diagnostic.get('coverage_ratio') is not None:
            st.metric('三欄財報診斷覆蓋率（非六項完整率）', f"{diagnostic['coverage_ratio'] * 100:.2f}%")
            st.caption(f"已知欄位 {diagnostic.get('known_fields')} / {diagnostic.get('expected_fields')}；母體 {diagnostic.get('stock_count')} 檔")
        st.info(summary.get('note', '六項完整率尚待核對。'))
    else:
        st.warning('Neon 統計 API 暫不可用；不顯示推估數字。')

    with st.form('v26_coverage_lookup'):
        symbol = st.text_input('個股代號（僅供既有資料查詢）', value='2330')
        lookup = st.form_submit_button('查看既有財報資料')
    if lookup:
        st.session_state.v26_coverage_symbol = symbol.strip().upper()
    target = st.session_state.get('v26_coverage_symbol')
    if target:
        coverage = api('GET', '/coverage/stock/' + target)
        if coverage and coverage.get('scope') == 'SIX_FACTOR_PERIOD_VERIFIED':
            st.markdown('#### 六項財報欄位完整率（Neon 初步檢查）')
            st.metric('已具備必要欄位與來源的項目', f"{coverage.get('complete_items', 0)} / {coverage.get('expected_items', 31)}")
            st.caption('此為暫定資料覆蓋率，尚未通過官方來源交叉驗證，不代表正式完整率。')
            missing = coverage.get('missing_years') or {}
            st.dataframe(pd.DataFrame([
                {'財務指標': FIELDS.get(field, field),
                 '缺漏年度': '、'.join(map(str, years)) if years else '無',
                 '狀態': '待補／待核對' if years else '欄位初步齊全'}
                for field, years in missing.items()
            ]), use_container_width=True, hide_index=True)
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
