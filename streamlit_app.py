"""只透過 API 存取使用者資料；個人金鑰只保存在目前 session。"""
import os,requests,pandas as pd
import streamlit as st
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
            r=requests.get(base+'/me',headers={'Authorization':'Bearer '+token},timeout=90);r.raise_for_status()
            st.session_state.token=token;st.rerun()
        except requests.RequestException: st.error('登入失敗：請確認金鑰或等候後端啟動後重試。')
    st.stop()
if st.sidebar.button('登出'):
    del st.session_state.token;st.rerun()
def api(method,path,**kwargs):
    try:
        r=requests.request(method,base+path,headers={'Authorization':'Bearer '+st.session_state.token},timeout=150,**kwargs)
        if r.status_code>=400:
            try: detail=r.json().get('detail','請稍後重試')
            except ValueError: detail='請稍後重試'
            st.error(str(detail));return None
        return r.json()
    except requests.RequestException:
        st.error('服務暫時無法連線，請稍後再試。');return None
query,watch,screen=st.tabs(['個股 / ETF 查詢','我的追蹤','市場選股'])
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
        st.metric(f"收盤價（{d['currency']}）",f"{d['price']:.2f}")
        st.caption(f"行情日 {d['date']}｜更新 {d['updated_at']}｜來源 {d['source']}｜種類 {d['kind']}")
        st.caption('價格口徑：'+d.get('price_basis','Yahoo還原價格用於技術條件；圖表為未還原收盤價'))
        if len(d['history']) > 1:
            st.line_chart(pd.DataFrame(d['history']).set_index('date'))
        else:
            st.info('目前僅有單日收盤價，歷史圖表待官方資料補齊。')
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
    if a.button('開啟每日摘要'):
        if api('POST','/notifications',json={'enabled':True}): st.success('已設定')
    if b.button('關閉每日摘要'):
        if api('POST','/notifications',json={'enabled':False}): st.success('已設定')
with screen:
    report=api('GET','/scan')
    if report:
        st.caption(f"更新 {report.get('updated_at')}｜{report.get('scope')}")
        st.metric('36小時內成功更新 / 母體',f"{report.get('fresh_count',0)} / {report.get('universe_size',0)}")
        st.write(f"本次嘗試 {report.get('attempted',0)} 檔；失敗 {len(report.get('failed',[]))} 檔")
        mode=st.radio('篩選模式',['income','swing'],format_func=lambda x:'存股' if x=='income' else '波段',horizontal=True)
        st.dataframe(pd.DataFrame({'符合條件標的':report.get(mode,[])}),use_container_width=True)
        with st.expander('本次失敗代號'): st.write(report.get('failed',[]))
    else: st.info('尚無掃描報告，請先執行排程。')
