"""Streamlit view of the authenticated downside research report."""
import re

import streamlit as st

BENCHMARKS = {
    'tw_electronics': '電子工業類指數',
    'tw_semiconductors': '半導體類指數',
    '2330.TW': '台積電（2330）',
    'nasdaq_100': 'Nasdaq-100',
    'sox': '費城半導體指數',
}
REPORT_STATUS = {
    'calendar_missing': '缺少可核對的歷史交易日曆。',
    'stock_history_missing': '這檔股票尚無已驗證的還原日線。',
}
BENCHMARK_STATUS = {
    'benchmark_history_missing': '缺少基準歷史行情',
    'publication_times_missing': '缺少逐日公布時間',
    'self_benchmark': '個股與基準相同，略過比較',
}
STATISTICS = (
    ('paired_coverage', '資料涵蓋率', '.1%'),
    ('pearson', 'Pearson', '.3f'),
    ('spearman', 'Spearman', '.3f'),
    ('up_probability', '逆勢上漲機率', '.1%'),
    ('down_market_mean', '逆勢平均報酬', '.2%'),
    ('severe_market_mean', '基準大跌時平均報酬', '.2%'),
    ('downside_beta', '下行 Beta', '.3f'),
)


def render(api, personal):
    if not personal:
        st.session_state.pop('defensive_report', None)
        st.info('請先登入個人功能，再查詢逆勢研究。')
        return

    with st.form('defensive_research'):
        symbol = st.text_input('台股代號', value='2330.TW', max_chars=12,
                               help='上市填 2330.TW，上櫃填 6488.TWO。')
        severe_drop = st.number_input('基準大跌門檻（%）', min_value=.1, max_value=100.,
                                       value=2., step=.1)
        submit = st.form_submit_button('查詢逆勢統計')
    if submit:
        st.session_state.pop('defensive_report', None)
        symbol = symbol.strip().upper()
        if not re.fullmatch(r'\d{4,6}[A-Z]?\.(TW|TWO)', symbol):
            st.error('請輸入含市場後綴的台股代號，例如 2330.TW 或 6488.TWO。')
            return
        with st.spinner('正在讀取已回補的行情與交易日曆…'):
            result = api('GET', '/defensive/research/' + symbol,
                         params={'severe_drop': severe_drop / 100})
        if result is not None:
            st.session_state['defensive_report'] = result

    saved = st.session_state.get('defensive_report')
    if saved is None:
        return
    result = saved
    if result['state'] != 'evaluated':
        st.warning(REPORT_STATUS.get(result['state'], '目前無法產生逆勢報告。'))
        return

    years = st.selectbox('統計期間', (1, 3, 5), format_func=lambda value: f'近 {value} 年')
    st.subheader(f"{result['symbol']} · 近 {years} 年")
    st.caption(f"統計截止 {result['as_of']}｜已回補日線截至 {result.get('stock_as_of') or '未提供'}"
               f"｜大跌門檻 {result['severe_drop']:.1%}｜每個基準至少 {result['min_pairs']} 組配對")
    rows = []
    for key, label in BENCHMARKS.items():
        benchmark = result['benchmarks'].get(key, {})
        stats = benchmark.get('periods', {}).get(str(years), {})
        state = BENCHMARK_STATUS.get(benchmark.get('state'), '資料未提供')
        if stats:
            state = '可計算' if stats['status'] == 'available' else '配對樣本不足'
        row = {'基準': label, '狀態': state,
               '配對／交易日': f"{stats['pairs']}／{stats['expected_sessions']}" if stats else '—',
               '下跌／大跌日': f"{stats['down_sessions']}／{stats['severe_sessions']}" if stats else '—'}
        for field, name, fmt in STATISTICS:
            value = stats.get(field)
            row[name] = format(value, fmt) if value is not None else '—'
        rows.append(row)
    st.dataframe(rows, hide_index=True)
    st.caption('台股基準使用同日收盤，供描述統計。美股基準依公布時間對齊下一個台灣開盤。')


def render_market_ranking(api, personal):
    if not personal:
        st.session_state.pop('defensive_market_snapshot', None)
        st.info('請先登入個人功能，再查看全市場逆勢排名。')
        return

    if st.button('讀取最新排名', key='load_defensive_market'):
        result = api('GET', '/defensive/market-ranking')
        if result is not None:
            st.session_state['defensive_market_snapshot'] = result
        elif st.session_state.get('defensive_market_snapshot'):
            st.warning('未能讀取最新排名，下方顯示上一次成功讀取的快照。')

    snapshot = st.session_state.get('defensive_market_snapshot')
    if snapshot is None:
        return
    if snapshot.get('state') != 'evaluated':
        st.info('目前沒有可讀取的全市場排名快照。')
        return

    coverage = snapshot['coverage']
    st.caption(f"收盤日 {snapshot['as_of']}｜產出時間 {snapshot['generated_at']}"
               f"｜具當日還原行情 {coverage['current_history']}／{coverage['universe']} 檔")
    period, group = st.columns(2)
    with period:
        years = st.selectbox('排名期間', (1, 3, 5), key='defensive_market_period',
                             format_func=lambda value: f'近 {value} 年')
    labels = {'combined': '五基準綜合榜', **BENCHMARKS}
    with group:
        key = st.selectbox('排名基準', tuple(labels), key='defensive_market_benchmark',
                           format_func=labels.__getitem__)

    periods = snapshot['periods']
    if 'screened_periods' in snapshot:
        use_screen = st.toggle('套用基本面與技術篩選', value=True, key='defensive_market_screen')
        counts = snapshot['screen_counts']
        st.caption(f"篩選通過 {counts['passed']} 檔｜未達規則 {counts['failed_rules']} 檔"
                   f"｜必要資料不足 {counts['missing_data']} 檔")
        if use_screen:
            periods = snapshot['screened_periods']
    ranking = periods[str(years)][key]
    if key == 'combined':
        unavailable = [label for code, label in BENCHMARKS.items()
                       if snapshot['benchmark_status'].get(code, {}).get('state') != 'evaluated']
        if unavailable:
            st.info('綜合榜仍缺少可用基準：' + '、'.join(unavailable))
            return
    else:
        state = snapshot['benchmark_status'].get(key, {}).get('state')
        if state != 'evaluated':
            st.info(BENCHMARK_STATUS.get(state, '基準資料未提供'))
            return

    threshold = snapshot['thresholds'][ranking['relaxation_tier']]
    st.caption(f"命中率門檻 {threshold:.0%}｜可評估 {ranking['eligible']} 檔｜符合 {ranking['matched']} 檔"
               f"｜至少 {snapshot['min_pairs']} 組配對及 {snapshot['min_down_sessions']} 個基準下跌日")
    if not ranking['items']:
        st.info('目前沒有個股具備足夠樣本。' if not ranking['eligible']
                else '目前沒有個股符合此榜單門檻。')
        return
    score_label = '加權逆勢命中率' if key == 'combined' else '逆勢上漲命中率'
    st.dataframe([
        {'名次': index, '股票代號': item['symbol'], score_label: format(item['score'], '.1%')}
        for index, item in enumerate(ranking['items'], start=1)
    ], hide_index=True)
    st.caption('命中率依歷史下跌日統計。綜合榜以五個基準的命中率加權計算。')


def render_line_preferences(api, personal):
    if not personal:
        st.session_state.pop('defensive_line_preference', None)
        st.session_state.pop('defensive_risk', None)
        st.info('請先登入個人功能，再設定 LINE 通知。')
        return
    if st.button('讀取 LINE 通知設定', key='load_defensive_line_preference'):
        st.session_state['defensive_line_preference'] = api('GET', '/defensive/line-preference')
        st.session_state['defensive_risk'] = api('GET', '/defensive/risk')
    risk = st.session_state.get('defensive_risk')
    if risk and risk.get('verified'):
        st.caption(f"最近一次已驗證的收盤風險 Level {risk['level']}｜交易日 {risk['session_date']}")
    elif risk:
        st.info('目前沒有已驗證的收盤風險資料。')
    saved = st.session_state.get('defensive_line_preference')
    if saved is None:
        return
    st.write('目前已開啟' if saved['enabled'] else '目前已關閉')
    label = '關閉逆勢通知' if saved['enabled'] else '開啟逆勢通知'
    if st.button(label, key='save_defensive_line_preference'):
        result = api('PUT', '/defensive/line-preference', json={'enabled': not saved['enabled']})
        if result is not None:
            st.session_state['defensive_line_preference'] = result
            st.rerun()
