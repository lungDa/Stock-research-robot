"""只透過 API 存取使用者資料；個人金鑰只保存在目前 session。"""
import os,requests,pandas as pd
import streamlit as st
from app.services.freshness import format_updated_at,quote_note
st.set_page_config(page_title='股海燈塔',page_icon='🌊',layout='wide')
st.title('🌊 股海燈塔')
st.caption('台美股・ETF｜存股與波段規則篩選')
try: base=st.secrets.get('API_BASE_URL',os.getenv('API_BASE_URL','http://localhost:10000'))
except FileNotFoundError: base=os.getenv('API_BASE_URL','http://localhost:10000')
def api(method,path,**kwargs):
    # 訪客只走公開GET端點；個人寫入端點仍由後端強制認證。
    if not st.session_state.get('personal_active') and method=='GET' and (path.startswith(('/quote/','/fundamentals/status/')) or path=='/scan'):
        path='/public'+path
    if not st.session_state.get('personal_active') and method=='POST' and path.startswith(('/fundamentals/prepare/','/fundamentals/request/')):
        path='/public'+path
    headers={'Authorization':'Bearer '+st.session_state.token} if st.session_state.get('token') else {}
    try:
        r=requests.request(method,base+path,headers=headers,timeout=45,**kwargs)
        if r.status_code>=400:
            try: detail=r.json().get('detail','請稍後重試')
            except ValueError: detail='請稍後重試'
            st.error(str(detail));return None
        return r.json()
    except requests.RequestException:
        st.error('服務暫時無法連線，請稍後再試。');return None

if st.query_params.get('login_code'):
    code=st.query_params['login_code'];st.query_params.clear()
    result=api('POST','/auth/redeem',json={'code':code})
    if result:
        st.session_state.clear()
        st.session_state.token=result['token'];st.session_state.login_name=result.get('name','LINE使用者')
        st.rerun()

st.session_state.personal_active=False
if st.session_state.get('token'):
    info=api('GET','/auth/me')
    if info:
        st.session_state.login_stage=info['stage'];st.session_state.login_name=info['name']
        st.session_state.password_change_required=info['password_change_required']
        st.session_state.is_admin=info.get('is_admin',False)
        st.session_state.personal_active=info['stage']=='active'
    else:
        st.session_state.clear()

with st.sidebar:
    if not st.session_state.get('token'):
        st.subheader('個人功能登入')
        st.caption('行情與選股免登入。個人功能先用LINE綁定身分，再驗證個人密碼。')
        if st.button('使用 LINE 登入個人功能'):
            result=api('POST','/auth/line/start',json={})
            if result:st.session_state.authorize_url=result['authorize_url']
        if st.session_state.get('authorize_url'):
            st.link_button('前往 LINE 認證',st.session_state.authorize_url)
            st.caption('請在2分鐘內開啟；LINE會在新頁面完成登入並返回。')
    elif st.session_state.get('login_stage')=='password':
        st.write('LINE身分：'+st.session_state.get('login_name',''))
        if st.session_state.get('password_change_required'):st.info('首次登入請輸入預設密碼0000，接著必須修改為8位數字。')
        with st.form('personal_password'):
            password=st.text_input('個人密碼',type='password',max_chars=8)
            verify=st.form_submit_button('驗證密碼')
        if verify:
            result=api('POST','/auth/password/verify',json={'password':password})
            if result:
                st.session_state.pop('result',None)
                st.rerun()
    elif st.session_state.get('login_stage')=='change_password':
        st.info('首次綁定完成，請先設定個人8位數字密碼。')
        with st.form('first_password_change'):
            new=st.text_input('新密碼（8位數字）',type='password',max_chars=8)
            confirm=st.text_input('再次輸入新密碼',type='password',max_chars=8)
            change=st.form_submit_button('設定密碼並開啟個人功能')
        if change:
            if new!=confirm:st.error('兩次新密碼不一致')
            elif api('POST','/auth/password/change',json={'new_password':new}):
                st.session_state.pop('result',None)
                st.rerun()
    else:
        st.write('已登入：'+st.session_state.get('login_name','LINE使用者'))
    if st.session_state.get('token') and st.button('登出'):
        api('POST','/auth/logout');st.session_state.clear();st.rerun()
personal=bool(st.session_state.get('personal_active'))
if not personal:st.caption('目前為公開模式：使用預設選股規則；個人清單、規則與通知需LINE登入並完成密碼設定。')
query,watch,screen,strategy_tab=st.tabs(['個股 / ETF 查詢','我的追蹤','市場選股','評分與通知設定'])
with query:
    with st.form('query'):
        symbol=st.text_input('代號','2330',help='上櫃例如 6488.TWO；美股例如 AAPL、VOO')
        submit=st.form_submit_button('分析')
    if submit:
        requested_symbol=symbol.strip()
        with st.spinner('正在取得行情並安排背景補資料…'):
            st.session_state.result=api('GET','/quote/'+requested_symbol)
            result=api('POST','/fundamentals/request/'+requested_symbol)
        st.session_state.download_result=result
        st.session_state.download_symbol=requested_symbol
        st.session_state.download_pending=bool(result and result.get('state') in ('queued','running'))
        if result:
            st.info(result['message'])
            if st.session_state.download_pending:st.toast('已開始背景補資料，可繼續查看行情。')
        st.session_state.download_notice_key=None

    @st.fragment(run_every='4s' if st.session_state.get('download_pending') else None)
    def download_progress():
        target=st.session_state.get('download_symbol')
        if not target:return
        previous=st.session_state.get('download_result') or {}
        result=api('GET','/fundamentals/status/'+target) if st.session_state.get('download_pending') else previous
        if not result:return
        st.session_state.download_result=result
        state=result.get('state')
        if state in ('queued','running'):
            st.info('基本面背景更新中；行情已先顯示，完成後將提醒。')
            return
        st.caption(result.get('message','')+f"｜已有資料集 {result.get('available_feeds',0)}/{result.get('total_feeds',0)}；資料集數不代表欄位完整度。")
        source_problem=result.get('official_annual_source',{})
        if source_problem.get('reason'):st.warning(source_problem['reason'])
        official=result.get('official_annual_status',{})
        if official:
            with st.expander('官方年度EPS／ROE下載狀態'):
                st.dataframe([{'欄位':name,'狀態':item.get('status','尚待下載'),'已涵蓋年度':'、'.join(item.get('years',[])),'說明':item.get('reason','')} for name,item in official.items()],hide_index=True)
        failed=[f for f in result.get('feeds',[]) if f.get('state')=='failed']
        partial=[f for f in result.get('feeds',[]) if f.get('state')=='partial']
        if partial:
            with st.expander('分批下載進度（排程會接續）'):
                st.dataframe([{'資料集':f['dataset'],'已保存紀錄':f.get('downloaded_records',0),'待下載區間':f.get('pending_windows',0),'說明':f.get('reason','')} for f in partial],hide_index=True)
        history=result.get('history_status',{})
        if history.get('remaining_months'):
            st.caption(f"歷史日線尚待回補 {history['remaining_months']} 個月份；完成後才依實際日線計算均線。")
        if failed:
            with st.expander('資料來源本批未完成原因'):
                st.dataframe([{'資料集':f['dataset'],'原因':f['reason'],'可重試倒數（秒）':f['retry_after_seconds']} for f in failed],hide_index=True)
        if st.session_state.get('download_pending'):
            st.session_state.download_pending=False
            refreshed=api('GET','/quote/'+target)
            if refreshed:st.session_state.result=refreshed
            st.session_state.download_notice_key='待提醒'
            st.rerun()
    download_progress()
    if st.session_state.get('download_notice_key')=='待提醒':
        result=st.session_state.get('download_result') or {}
        st.toast('本批背景更新完成。' if result.get('state')=='updated' else '本批處理結束，仍有資料待補；請查看缺漏原因。')
        st.session_state.download_notice_key='已提醒'
    d=st.session_state.get('result')
    if d:
        for warning in d.get('warnings', []): st.warning(warning)
        st.subheader(f"{d['name']} · {d['symbol']}")
        st.info(quote_note(d))
        if d.get('price') is None:st.info('目前僅有年度財報，尚無可用行情；下方仍可查看基本面。')
        else:st.metric(f"收盤價（{d['currency']}）",f"{d['price']:.2f}")
        st.caption(f"行情日 {d['date']}｜更新 {format_updated_at(d.get('updated_at'))}｜來源 {d['source']}｜種類 {d['kind']}")
        st.caption('價格口徑：'+d.get('price_basis','Yahoo還原價格用於技術條件；圖表為未還原收盤價'))
        if len(d['history']) > 1:
            st.line_chart(pd.DataFrame(d['history']).set_index('date'))
        else:
            st.info('目前僅有單日收盤價，歷史圖表待官方資料補齊。')
        if d.get('kind')=='STOCK':
            st.subheader('近一年基本面（TTM／近365天）')
            trailing=d.get('trailing_details',{})
            names={'eps_ttm':'EPS（TTM／報表幣別每股）','roe_ttm_pct':'ROE（TTM／%）','paid_yield_pct':'近365天已到發放日配息率（%）'}
            st.dataframe([{'項目':label,'數值':trailing.get(key,{}).get('value'),
                '起日':trailing.get(key,{}).get('period_start',''),'迄日':trailing.get(key,{}).get('period_end',''),
                '股價日':trailing.get(key,{}).get('price_date',''),'來源':trailing.get(key,{}).get('source',''),
                '口徑':trailing.get(key,{}).get('basis','缺少可核對的近一年資料')} for key,label in names.items()],hide_index=True)
            st.caption('TTM財報期間與配息365天區間可能不同；多年平均EPS／ROE等個人選股規則仍使用年度資料，不以TTM替代。')
            evidence={names[key]:value.get('calculation') for key,value in trailing.items() if key in names and value.get('calculation')}
            if evidence:
                with st.expander('核對TTM EPS／ROE的計算依據'):
                    st.json(evidence)
        with st.expander('分類與基本面來源 / 期間'):
            labels={'kind':'商品分類','fund_type':'基金類型','eps':'財報累計EPS（元）','pe':'官方本益比','official_yield':'官方公告殖利率（%）','reported_roe':'報表ROE（小數；僅展示）'}
            details=d.get('fundamental_details',{})
            if details:
                st.dataframe([{'項目':labels.get(k,k),'值':str(v['value']),'期間':v.get('period','未提供'),'出表日期':v['as_of'],'說明':v.get('basis',''),'來源':v['source']} for k,v in details.items()],hide_index=True)
            else: st.info('基本面共用快取尚未載入，待排程分批更新。')
            st.caption('此區為官方快照：財報EPS為年初至本季累計，未換算年化或TTM；官方殖利率與期間不明ROE僅供檢視。歷年資料見下方；ETF年度總費用率仍可能缺資料。')
            if d.get('fund_profile'):st.caption(d['fund_profile'].get('note',''))
        rating=d.get('rating')
        if rating:
            st.subheader('多因子分級：'+rating['grade'])
            st.write(f"有效資料分數：{rating['score']}｜資料完整度：{rating['coverage']}%")
            if d.get('annual_sources'):
                with st.expander('歷年基本面與來源（人工匯入另行標示）'):
                    st.dataframe([{k:v for k,v in row.items() if k!='field_sources'} for row in d['annual_sources']],hide_index=True)
                    field_sources=[]
                    for year,row in d.get('annual_rows',{}).items():
                        for field,source in row.get('field_sources',{}).items():
                            field_sources.append({'年度':year,'欄位':{'eps':'年度EPS','roe_pct':'年度ROE'}.get(field,field),
                                '數值':row.get(field),'期間起日':source.get('period_start',row.get('period_start','')),
                                '期間迄日':source.get('period_end',row.get('period_end','')),
                                '單位':source.get('unit',''),'來源':source.get('url',''),
                                '口徑':source.get('basis',''),'資料類型':source.get('provenance','')})
                    if field_sources:
                        st.caption('每個欄位的來源與期間（EPS及ROE可能使用不同來源）')
                        st.dataframe(field_sources,hide_index=True)
                    annual=d.get('annual_rows',{})
                    if annual:
                        labels={'eps':'年度EPS','roe_pct':'ROE（%）','cash_yield_pct':'年度現金殖利率（%）',
                            'cash_dividend_per_share':'年度已到發放日現金股利／股',
                            'operating_cash_flow':'營業現金流','capital_expenditure':'資本支出',
                            'cash_dividends_paid':'現金股利支出','revenue':'年度營收','currency':'幣別'}
                        st.dataframe([{'年度':y,**{label:r.get(key) for key,label in labels.items()}}
                            for y,r in sorted(annual.items(),reverse=True)],hide_index=True)
                    state=d.get('annual_refresh',{})
                    if state.get('updated_at'):st.caption('共用年度資料更新：'+format_updated_at(state['updated_at']))
                    for note in state.get('notes',[]):st.caption(note)
                    st.caption('五年殖利率口徑：各年已到發放日的現金股利／該年未還原年底收盤價，再取平均；美股EPS門檻以USD／股計，台股以TWD／股計。缺少欄位留白，不視為零。')
            st.caption('分數僅計已知資料；必要條件缺漏或行情過舊時，一律不取得買入級別。')
            st.caption(rating.get('reason',''))
            st.dataframe([{'因子':x['label'],'期間（年）':x['years'],'實際值':x['value'],'門檻':str(x['op'])+' '+str(x['threshold']),'結果':'缺資料' if x['passed'] is None else ('符合' if x['passed'] else '未符合'),'必要':x['required'],'權重':x['weight']} for x in rating['checks']],hide_index=True)
        quality=d.get('data_quality',{})
        with st.expander('各欄資料狀態與缺漏原因',expanded=bool(quality.get('required_missing'))):
            labels={'available':'可計算','unsupported':'尚未支援','verification_required':'需核對補登',
                    'cooldown':'來源冷卻','not_configured':'來源未設定','history_missing':'歷史／行情不足','missing':'待補資料','queued':'已排程'}
            fields=quality.get('current_fields',[])+quality.get('rule_fields',[])
            st.dataframe([{'項目':x['label'],'狀態':labels.get(x['state'],x['state']),
                '缺漏年度':'、'.join(map(str,x.get('missing_years',[]))),'說明':x['reason']} for x in fields],hide_index=True)
            st.caption('已安排下載不代表來源一定涵蓋；TTM EPS需核對股數基準，年度EPS不替代。')
        cols=st.columns(2)
        for col,mode,title in zip(cols,['income','swing'],['近一年簡易檢核','波段條件']):
            with col:
                st.markdown('### '+title)
                st.write(f"符合 {d[mode]['score']} / {d[mode]['total']}")
                st.table([{'條件':k,'結果':'缺資料' if v is None else ('符合' if v else '未符合')} for k,v in d[mode]['checks'].items()])
        st.caption('近一年配息率為歷史現金配息／目前價格；不是未來收益承諾。ETF 配息不等同總報酬。')
        if personal and st.button('加入我的追蹤'): 
            if api('POST','/watchlist',json={'symbol':d['symbol']}): st.success('已加入')
with watch:
    if not personal:
        st.info('請先在左側完成LINE登入與個人密碼設定，再使用追蹤清單及通知。')
    else:
        items=api('GET','/watchlist')
        if items:
            chosen=st.selectbox('已追蹤標的',items)
            if st.button('移除追蹤'):
                api('DELETE','/watchlist/'+chosen);st.rerun()
        else: st.info('尚無追蹤標的，請先查詢並加入。')
        a,b=st.columns(2)
        if a.button('開啟升降級通知'):
            if api('POST','/notifications',json={'enabled':True}): st.success('已設定；請確認已加入股海燈塔LINE官方帳號為好友。')
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
        mode=st.radio('篩選模式',['income','swing'],format_func=lambda x:'多因子存股' if x=='income' else '波段',horizontal=True)
        st.dataframe(pd.DataFrame({'符合條件標的':report.get(mode,[])}),use_container_width=True)
        with st.expander('本次失敗代號'): st.write(report.get('failed',[]))
    else: st.info('尚無掃描報告，請先執行排程。')

with strategy_tab:
    if not personal:
        st.info('請先在左側完成LINE登入與個人密碼設定，再調整個人需求。')
    else:
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
        st.subheader('LINE主動助理')
        if 'assistant_config' not in st.session_state:
            loaded=api('GET','/assistant/preferences')
            if isinstance(loaded,dict) and 'daily_brief' in loaded:st.session_state.assistant_config=loaded
        prefs=st.session_state.get('assistant_config')
        if prefs:
            with st.form('assistant_preferences'):
                brief=st.checkbox('沒有單檔訊號時，盤後補一則追蹤摘要',value=prefs['daily_brief'])
                empty=st.checkbox('清單空白時引導建立追蹤（最多7天一次）',value=prefs['empty_reminder'])
                saved=st.form_submit_button('儲存LINE助理設定')
            if saved:
                result=api('PUT','/assistant/preferences',json={'daily_brief':brief,'empty_reminder':empty})
                if result:st.session_state.assistant_config=result;st.success('已儲存LINE助理設定。')
        st.caption('需已開啟LINE通知。平日18:17後檢查，實際推播時間依排程及來源；與升降級訊號共用每日上限，沒有完整資料不給假買入建議。')
        st.divider()
        st.subheader('補登台股年度 EPS 與現金股利支出')
        st.link_button('開啟公開資訊觀測站查核年報','https://mops.twse.com.tw/')
        st.caption('請核對官方完整年度合併財報：EPS填全年基本EPS，不填第四季單季值或TTM；股利支出填現金流量表的全年支付總額。')
        st.caption('EPS以TWD／股計。股利支出會依下方單位換算為元，與自動下載的現金流保持一致。補登只影響你的分級；不會覆蓋共用資料。')
        from app.services.freshness import local_now
        with st.form('annual_supplement_form'):
            supplement_symbol=st.text_input('補登台股代號','2330',key='supplement_symbol')
            unit_label=st.selectbox('這次填寫的現金股利支出單位',['元','千元','百萬元'])
            last_year=local_now().year-1
            edited=st.data_editor(pd.DataFrame([{'year':y,'eps':None,'cash_dividends_paid':None,'source_url':''}
                for y in range(last_year,last_year-10,-1)]),hide_index=True,disabled=['year'],
                column_config={'year':st.column_config.NumberColumn('年度',format='%d'),
                'eps':st.column_config.NumberColumn('全年基本EPS（TWD／股）'),
                'cash_dividends_paid':st.column_config.NumberColumn('全年支付現金股利總額',min_value=0.0),
                'source_url':st.column_config.TextColumn('該年度官方年報／財報HTTPS網址')},key='annual_supplement_grid')
            checked=st.checkbox('我已核對公司、完整年度與合併範圍；股利支出是支付總額，並已選對單位')
            save_supplement=st.form_submit_button('儲存有填寫的年度（保留其他資料）')
        if save_supplement:
            rows=[]
            for _,r in edited.iterrows():
                values={k:float(r[k]) for k in ('eps','cash_dividends_paid') if pd.notna(r[k])}
                if values:rows.append({'year':int(r['year']),**values,'source_url':str(r['source_url'] or '')})
            if not rows:st.error('請至少填入一項年度EPS或股利支出。')
            elif not checked:st.error('請先核對資料並勾選確認。')
            else:
                result=api('PATCH','/annual-supplement/'+supplement_symbol.strip(),json={'confirmed':True,
                    'unit':{'元':'TWD','千元':'TWD_THOUSAND','百萬元':'TWD_MILLION'}[unit_label],'rows':rows})
                if result:
                    st.session_state.pop('result',None)
                    st.success('已補登年度：'+', '.join(result['years'])+'；請重新分析查看個人評分。')
        if st.button('查看我的補登資料'):
            saved=api('GET','/annual-supplement/'+supplement_symbol.strip())
            if saved:
                st.caption('下表股利支出已統一換算為元；重填時請留意單位。')
                st.dataframe(saved['rows'],hide_index=True)
        st.divider()
        st.subheader('核對補登近一年 EPS（台股／美股）')
        st.caption('僅在有可核對的TTM來源時使用。請先確認近四季股數基準一致；不能把全年、第四季單季或不同股數基準的EPS直接當TTM。此處只影響你的近一年EPS，不覆蓋年度資料。')
        with st.form('ttm_eps_form'):
            ttm_symbol=st.text_input('近一年EPS代號','2330',key='ttm_symbol')
            from datetime import timedelta
            from datetime import date
            latest_end=local_now().date().replace(day=1,month=((local_now().month-1)//3)*3+1)-timedelta(days=1)
            latest_start=date(latest_end.year-1,latest_end.month,latest_end.day)+timedelta(days=1)
            ttm_start=st.date_input('TTM期間起日',value=latest_start)
            ttm_end=st.date_input('TTM期間迄日',value=latest_end)
            ttm_value=st.number_input('已核對的近一年EPS（報表幣別／股）',value=None,step=0.01)
            ttm_source=st.text_input('近一年EPS官方財報來源HTTPS網址')
            ttm_check=st.checkbox('我已核對近一年起訖期間與股數基準；數值不是單季或預估EPS')
            ttm_save=st.form_submit_button('儲存已核對的TTM EPS')
        if ttm_save:
            if ttm_value is None or not ttm_check:st.error('請填EPS並核對期間與股數基準。')
            elif api('PUT','/ttm-eps/'+ttm_symbol.strip(),json={'confirmed':True,'value':ttm_value,
                'period_start':str(ttm_start),'period_end':str(ttm_end),'source':ttm_source}):
                st.session_state.pop('result',None);st.success('TTM EPS已保存，請重新分析。')
        st.divider()
        st.subheader('台股TTM EPS：獲利與加權股數核對計算')
        st.caption('適用於你已核對四個完整單季、普通股可分配損益與同一拆配股基準的情況。程式檢查期間、單位與算式；財報內容及重編股數依據由你核對，不代表系統自動查證。')
        with st.form('ttm_components_form'):
            proof_symbol=st.text_input('核對計算股票代號','6488.TWO',key='proof_symbol')
            from datetime import date,timedelta
            end=local_now().date().replace(day=1,month=((local_now().month-1)//3)*3+1)-timedelta(days=1)
            last_q=(end.year*4+(end.month-1)//3)
            defaults=[]
            for i in range(3,-1,-1):
                y,q=divmod(last_q-i,4)
                start=date(y,q*3+1,1)
                end_month=(q+1)*3
                stop=date(y+1,1,1)-timedelta(days=1) if end_month==12 else date(y,end_month+1,1)-timedelta(days=1)
                defaults.append({'period_start':str(start),'period_end':str(stop),'ordinary_profit':None,
                    'weighted_average_shares':None,'reported_basic_eps':None,'source':''})
            proof_frame=pd.DataFrame(defaults)
            for key in ('ordinary_profit','weighted_average_shares','reported_basic_eps'):proof_frame[key]=proof_frame[key].astype(float)
            proof_rows=st.data_editor(proof_frame,num_rows='fixed',hide_index=True,key='ttm_components_grid',column_config={
                'period_start':st.column_config.TextColumn('單季起日'),'period_end':st.column_config.TextColumn('單季迄日'),
                'ordinary_profit':st.column_config.NumberColumn('普通股可分配損益'),
                'weighted_average_shares':st.column_config.NumberColumn('加權平均普通股股數',min_value=0.0),
                'reported_basic_eps':st.column_config.NumberColumn('同基準單季基本EPS（選填）'),
                'source':st.column_config.TextColumn('該季財報HTTPS來源')})
            st.caption('損益須歸屬普通股，並已處理特別股等調整；股數須為單季加權平均股數。單季基本EPS為選填，僅用來交叉檢查算式。每季須附財報來源，不能填年初累計損益。')
            proof_money=st.selectbox('四季損益單位',['元','千元','百萬元'],key='proof_money')
            proof_shares=st.selectbox('四季股數單位',['股','千股','百萬股'],key='proof_shares')
            proof_basis_source=st.text_input('同一拆配股基準／重編依據的財報HTTPS網址')
            proof_basis_date=st.date_input('股數基準核對日期',value=local_now().date())
            proof_income_checked=st.checkbox('我已核對為歸屬普通股可分配損益，並已處理特別股等調整')
            proof_shares_checked=st.checkbox('我已核對四季股數均已依同一拆股／配股基準調整，並提供依據')
            proof_checked=st.checkbox('我已核對股票、四個連續單季、幣別及單位')
            proof_submit=st.form_submit_button('驗證算式並儲存我的TTM EPS')
        if proof_submit:
            quarters=[]
            for _,row in proof_rows.iterrows():
                item={'period_start':str(row['period_start']),'period_end':str(row['period_end']),'source':str(row['source'] or '')}
                for key in ('ordinary_profit','weighted_average_shares','reported_basic_eps'):
                    item[key]=float(row[key]) if pd.notna(row[key]) else None
                quarters.append(item)
            result=api('PUT','/ttm-eps-components/'+proof_symbol.strip(),json={'quarters':quarters,'currency':'TWD',
                'money_unit':{'元':'TWD','千元':'TWD_THOUSAND','百萬元':'TWD_MILLION'}[proof_money],
                'share_unit':{'股':'SHARES','千股':'THOUSAND_SHARES','百萬股':'MILLION_SHARES'}[proof_shares],
                'share_basis_source':proof_basis_source,'share_basis_date':str(proof_basis_date),
                'ordinary_profit_confirmed':proof_income_checked,'share_basis_confirmed':proof_shares_checked,'confirmed':proof_checked})
            if result:
                st.session_state.pop('result',None)
                st.success(f"核對計算TTM EPS：{result['value']:.4f} 元／股，已保存為你的核對資料。")
                st.json(result['calculation'])
        st.divider()
        st.subheader('匯入個人年度歷史資料')
        st.info('共用資料已分批下載；仍缺的年度欄位可由官方年報核對後補登或匯入。人工資料不代表系統已自動驗證，只影響你的分級。')
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

        st.divider()
        st.subheader('修改個人密碼')
        with st.form('change_own_password'):
            current_pw=st.text_input('目前密碼',type='password',max_chars=8)
            next_pw=st.text_input('新的8位數字密碼',type='password',max_chars=8)
            next_confirm=st.text_input('再次確認新密碼',type='password',max_chars=8)
            change_pw=st.form_submit_button('修改密碼')
        if change_pw:
            if next_pw!=next_confirm:st.error('兩次新密碼不一致')
            elif api('POST','/auth/password/change',json={'current_password':current_pw,'new_password':next_pw}):st.success('密碼已修改，其他登入工作階段將失效。')


if personal:
    with st.expander('我的帳戶資訊（管理者設定用）'):
        if st.button('顯示我的LINE識別碼'):
            account=api('GET','/me')
            if account:st.code(account['user'],language=None)


if personal and st.session_state.get('is_admin'):
    with st.expander('管理者：資料更新與系統狀態'):
        if st.button('檢查資料更新狀態'):
            status=api('GET','/admin/status')
            if status:st.session_state.operations_status=status
        status=st.session_state.get('operations_status')
        if status:
            left,right=st.columns(2)
            left.metric('有效查詢需求',status['queue_symbols'])
            right.metric('最早需求距今（小時）',status['oldest_request_age_hours'])
            st.caption(status['queue_scope'])
            st.write('來源設定：',status['source_configured'])
            st.write('今日來源請求／本系統上限：',status['daily_provider_requests'])
            st.write('來源可重試倒數（秒）：',status['source_retry_after_seconds'])
            st.dataframe([{'工作':name,'最後結束':item.get('updated_at','尚無紀錄'),
                '狀態':item.get('state','詳見紀錄')} for name,item in status['jobs'].items()],hide_index=True)
            st.write('最近掃描：',status['scan'])
            st.caption(status['field_coverage_scope'])
            st.dataframe([{'欄位':x['label'],'有值檔數':x['known'],'抽樣檔數':x['sampled'],'完整率（%）':x['coverage_pct']} for x in status['field_coverage_sample']],hide_index=True)
            st.caption(f"資料集抽樣 {status['feed_states_sampled']} 筆（上限 {status['feed_sample_limit']}）；成功 {status['feed_ok']}，失敗 {status['feed_failed']}。")
