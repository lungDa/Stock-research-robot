"""只透過 API 存取使用者資料；個人金鑰只保存在目前 session。"""
import os,requests,pandas as pd
import streamlit as st
from app.services.freshness import format_updated_at,quote_note
st.set_page_config(page_title='股海燈塔',page_icon='🌊',layout='wide')
st.title('🌊 股海燈塔')
st.caption('台美股・ETF｜存股與波段規則篩選')
try: base=st.secrets.get('API_BASE_URL',os.getenv('API_BASE_URL','http://localhost:10000'))
except FileNotFoundError: base=os.getenv('API_BASE_URL','http://localhost:10000')
if 'token' not in st.session_state:
    with st.form('login'):
        token=st.text_input('個人存取金鑰',type='password')
        ok=st.form_submit_button('登入')
    if ok:
        try:
            r=requests.get(base+'/me',headers={'Authorization':'Bearer '+token},timeout=45);r.raise_for_status()
            st.session_state.token=token;st.rerun()
        except requests.RequestException: st.error('登入失敗：請確認金鑰或等候後端啟動後重試。')
    st.stop()
if st.sidebar.button('登出'):
    st.session_state.clear();st.rerun()
def api(method,path,**kwargs):
    try:
        r=requests.request(method,base+path,headers={'Authorization':'Bearer '+st.session_state.token},timeout=45,**kwargs)
        if r.status_code>=400:
            try: detail=r.json().get('detail','請稍後重試')
            except ValueError: detail='請稍後重試'
            st.error(str(detail));return None
        return r.json()
    except requests.RequestException:
        st.error('服務暫時無法連線，請稍後再試。');return None
query,watch,screen,strategy_tab=st.tabs(['個股 / ETF 查詢','我的追蹤','市場選股','評分與通知設定'])
with query:
    with st.form('query'):
        symbol=st.text_input('代號','2330',help='上櫃例如 6488.TWO；美股例如 AAPL、VOO')
        submit=st.form_submit_button('分析')
    if submit:
        with st.spinner('取得資料中…'): st.session_state.result=api('GET','/quote/'+symbol.strip())
    d=st.session_state.get('result')
    if d:
        for warning in d.get('warnings', []): st.warning(warning)
        st.subheader(f"{d['name']} · {d['symbol']}")
        st.info(quote_note(d))
        st.metric(f"收盤價（{d['currency']}）",f"{d['price']:.2f}")
        st.caption(f"行情日 {d['date']}｜更新 {format_updated_at(d.get('updated_at'))}｜來源 {d['source']}｜種類 {d['kind']}")
        st.caption('價格口徑：'+d.get('price_basis','Yahoo還原價格用於技術條件；圖表為未還原收盤價'))
        if len(d['history']) > 1:
            st.line_chart(pd.DataFrame(d['history']).set_index('date'))
        else:
            st.info('目前僅有單日收盤價，歷史圖表待官方資料補齊。')
        with st.expander('分類與基本面來源 / 期間'):
            labels={'kind':'商品分類','fund_type':'基金類型','eps':'財報累計EPS（元）','pe':'官方本益比','official_yield':'官方公告殖利率（%）','reported_roe':'報表ROE（小數；僅展示）'}
            details=d.get('fundamental_details',{})
            if details:
                st.dataframe([{'項目':labels.get(k,k),'值':str(v['value']),'期間':v.get('period','未提供'),'出表日期':v['as_of'],'說明':v.get('basis',''),'來源':v['source']} for k,v in details.items()],hide_index=True)
            else: st.info('基本面共用快取尚未載入，待排程分批更新。')
            st.caption('財報EPS為年初至本季累計，未換算年化或TTM；官方殖利率與期間不明ROE僅供檢視。年度總費用率及完整近一年已發配息尚未接入。')
        rating=d.get('rating')
        if rating:
            st.subheader('多因子分級：'+rating['grade'])
            st.write(f"有效資料分數：{rating['score']}｜資料完整度：{rating['coverage']}%")
            if d.get('annual_sources'):
                with st.expander('年度資料來源（人工匯入未經自動驗證）'):
                    st.dataframe(d['annual_sources'],hide_index=True)
            st.caption('缺資料模式為封鎖時，部分分數再高也不代表取得買入級別。')
            st.dataframe([{'因子':x['label'],'期間（年）':x['years'],'實際值':x['value'],'門檻':str(x['op'])+' '+str(x['threshold']),'結果':'缺資料' if x['passed'] is None else ('符合' if x['passed'] else '未符合'),'必要':x['required'],'權重':x['weight']} for x in rating['checks']],hide_index=True)
        cols=st.columns(2)
        for col,mode,title in zip(cols,['income','swing'],['存股條件','波段條件']):
            with col:
                st.markdown('### '+title)
                st.write(f"符合 {d[mode]['score']} / {d[mode]['total']}")
                st.table([{'條件':k,'結果':'缺資料' if v is None else ('符合' if v else '未符合')} for k,v in d[mode]['checks'].items()])
        st.caption('近一年配息率為歷史現金配息／目前價格；不是未來收益承諾。ETF 配息不等同總報酬。')
        if st.button('加入我的追蹤'): 
            if api('POST','/watchlist',json={'symbol':d['symbol']}): st.success('已加入')
with watch:
    items=api('GET','/watchlist')
    if items:
        chosen=st.selectbox('已追蹤標的',items)
        if st.button('移除追蹤'):
            api('DELETE','/watchlist/'+chosen);st.rerun()
    else: st.info('尚無追蹤標的，請先查詢並加入。')
    a,b=st.columns(2)
    if a.button('開啟升降級通知'):
        if api('POST','/notifications',json={'enabled':True}): st.success('已設定')
    if b.button('關閉升降級通知'):
        if api('POST','/notifications',json={'enabled':False}): st.success('已設定')
with screen:
    report=api('GET','/scan')
    if report:
        st.caption(f"更新 {report.get('updated_at')}｜{report.get('scope')}")
        st.metric('本次有效資料 / 母體' if 'budget_seconds' in report else '36小時內成功更新 / 母體',f"{report.get('fresh_count',0)} / {report.get('universe_size',0)}")
        st.write(f"本次嘗試 {report.get('attempted',0)} 檔；失敗 {len(report.get('failed',[]))} 檔")
        if report.get('ratings'):
            st.subheader('本次批次多因子分級（依你的設定）')
            st.dataframe([{'代號':x['symbol'],'名稱':x['name'],'分級':x['rating']['grade'],'有效資料分數':x['rating']['score'],'完整度':x['rating']['coverage']} for x in report['ratings']],hide_index=True)
        mode=st.radio('篩選模式',['income','swing'],format_func=lambda x:'存股' if x=='income' else '波段',horizontal=True)
        st.dataframe(pd.DataFrame({'符合條件標的':report.get(mode,[])}),use_container_width=True)
        with st.expander('本次失敗代號'): st.write(report.get('failed',[]))
    else: st.info('尚無掃描報告，請先執行排程。')

with strategy_tab:
    from app.services.multifactor import DEFAULT,METRICS
    import copy
    st.subheader('個人多因子規則')
    st.caption('設定只影響你的分級與追蹤通知。條件可新增、刪除、停用、調整門檻、期間、權重及必要條件。')
    if 'strategy_config' not in st.session_state:
        loaded=api('GET','/strategy')
        if isinstance(loaded,dict) and 'stock_rules' in loaded:st.session_state.strategy_config=loaded
    config=st.session_state.get('strategy_config')
    if config:
        names={v:k for k,v in METRICS.items()}
        with st.form('strategy_form'):
            edited=copy.deepcopy(config)
            policy=st.selectbox('資料不足時',['block','available'],index=0 if config['missing_policy']=='block' else 1,format_func=lambda x:'不分級，顯示資料不足' if x=='block' else '只評已有資料，最高為買')
            a,b=st.columns(2)
            buy=a.number_input('買：最低分數',min_value=1.,max_value=99.,value=float(config['buy_score']))
            strong=b.number_input('強力買：最低分數',min_value=2.,max_value=100.,value=float(config['strong_score']))
            for section,title in [('stock_rules','個股條件'),('etf_rules','ETF條件')]:
                st.markdown('#### '+title)
                ui=[{**r,'metric':METRICS[r['metric']]} for r in config[section]]
                permitted=[METRICS[k] for k in METRICS if (k in {'eps_latest','eps_avg','yield_avg','dividend_streak','roe_avg','fcf_positive','fcf_coverage','revenue_cagr','price_ma20','ma20_ma60'}) == (section=='stock_rules') or (section=='etf_rules' and k in {'price_ma20','ma20_ma60'})]
                frame=st.data_editor(pd.DataFrame(ui),num_rows='dynamic',key='rules_'+section,hide_index=True,column_config={
                    'metric':st.column_config.SelectboxColumn('因子',options=permitted,required=True),
                    'threshold':st.column_config.NumberColumn('門檻',required=True),
                    'years':st.column_config.NumberColumn('期間（年）',min_value=1,max_value=10,step=1,required=True),
                    'op':st.column_config.SelectboxColumn('比較',options=['>','>=','<','<=','=='],required=True),
                    'weight':st.column_config.NumberColumn('權重',min_value=1,max_value=100,required=True),
                    'enabled':st.column_config.CheckboxColumn('啟用',required=True),
                    'required':st.column_config.CheckboxColumn('必要條件',required=True)})
                edited[section]=frame.to_dict('records')
            st.caption('自由現金流正值條件使用 == 1；覆蓋率使用 ≥ 1。營收5年CAGR需要6個連續年度。年度現金殖利率請使用各年度實際現金股利／一致口徑年度股價；百分比輸入5代表5%。')
            direction=st.selectbox('重要訊號',['both','up'],index=0 if config['notify_direction']=='both' else 1,format_func=lambda x:'升級與降級都通知' if x=='both' else '只通知升級')
            cap=st.number_input('每人每日最多幾則（每檔獨立訊息）',min_value=1,max_value=10,value=int(config['daily_cap']))
            st.caption('預設只通知追蹤標的，同級不重送；首次觀望或資料不足不通知。修改規則後建立新基準，避免設定變動造成洗版。配額或時間用完時，尚未送出的最新變化留待下次檢查。')
            save=st.form_submit_button('儲存個人設定')
        if save:
            try:
                for section in ('stock_rules','etf_rules'):
                    for r in edited[section]:
                        r['metric']=names[r['metric']];r['years']=int(r['years'])
                edited.update(missing_policy=policy,buy_score=buy,strong_score=strong,notify_direction=direction,daily_cap=int(cap))
                from app.services.multifactor import validate
                validate(edited)
                result=api('PUT','/strategy',json=edited)
                if result:
                    st.session_state.strategy_config=result
                    st.session_state.pop('result',None)
                    st.success('已儲存；請重新分析股票，排程通知也會使用新設定。')
            except (ValueError,TypeError,KeyError) as exc:st.error('請填完整規則；'+str(exc))
    st.divider()
    st.subheader('匯入個人年度歷史資料')
    st.info('目前官方快取以最新季度為主，未自動補齊5～10年資料。此處匯入的是你提供的年度數據，不代表已經官方驗證；只影響你的分級。')
    columns='year,eps,roe_pct,cash_yield_pct,cash_dividend_per_share,operating_cash_flow,capital_expenditure,cash_dividends_paid,revenue,source_url\n'
    st.download_button('下載空白CSV欄位範本',columns,'annual_history_template.csv','text/csv')
    st.caption('每列一個完整西元年度、每年附來源網址，空白表示缺值。ROE及殖利率用百分點；資本支出填正數支出。營收、營業現金流、資本支出、支付現金股利總額必須同幣別同單位、同合併範圍。現金股利每股與總額不可混填。')
    with st.form('annual_import'):
        import_symbol=st.text_input('匯入股票代號','2330',key='annual_symbol')
        uploaded=st.file_uploader('年度CSV（128KiB內，最多15年）',type=['csv'])
        import_ok=st.form_submit_button('驗證並取代這檔的個人年度資料')
    if import_ok:
        if uploaded is None:st.error('請選擇CSV')
        elif uploaded.size>131072:st.error('CSV超過128KiB')
        else:
            result=api('POST','/annual/'+import_symbol.strip(),data=uploaded.getvalue())
            if result:
                st.session_state.pop('result',None)
                st.success('已匯入年度：'+', '.join(result['years'])+'；請重新分析。')
    if st.button('載入我的追蹤分級（只讀快取）'):
        results=api('GET','/ratings')
        if results:
            st.dataframe([{'代號':x['symbol'],'名稱':x['name'],'分級':x['rating']['grade'],'有效資料分數':x['rating']['score'],'完整度':x['rating']['coverage']} for x in results],hide_index=True)
