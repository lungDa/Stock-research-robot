"""Explicit snapshot forms; no automatic Agent execution."""
import os,json,time,hashlib,uuid
import streamlit as st
LABELS={"system_monitor":"系統監控","data_auditor":"財務資料品質","notification":"通知稽核","recovery":"復原建議","research":"投資研究","risk":"投資風險"}
def clear():
    for k in list(st.session_state):
        if k.startswith("agent_manager_"):st.session_state.pop(k,None)
def field(name,label,default):
    return json.loads(st.text_area(label,json.dumps(default,ensure_ascii=False),key="agent_manager_"+name,max_chars=200000))
def snapshot(name):
    if name=="system_monitor":
        ready=st.selectbox("資料庫狀態",["未知","正常","異常"],key="agent_manager_ready")
        return {"database_ready":{"未知":None,"正常":True,"異常":False}[ready],"failed_jobs":int(st.number_input("失敗工作數",min_value=0,step=1,key="agent_manager_failed")),"stale_jobs":int(st.number_input("過期工作數",min_value=0,step=1,key="agent_manager_stale"))}
    if name=="data_auditor":
        return {"symbols":st.text_input("股票代碼（逗號分隔）",key="agent_manager_symbols").split(","),"documents":field("audit_docs","財務證據快照",{})}
    if name=="notification":
        return {"days":int(st.number_input("稽核天數",min_value=1,max_value=14,key="agent_manager_days")),"users":field("users","匿名化使用者快照",[]),"documents":field("notify_docs","通知證據快照",{})}
    if name=="recovery":
        return {k:field("recovery_"+k,label,{}) for k,label in [("monitor","監控報告"),("data","資料稽核報告"),("notification","通知稽核報告")]}
    if name=="research":
        return {"symbol":st.text_input("股票代碼",key="agent_manager_symbol"),"quote":field("quote","行情快照",{}),"documents":field("research_docs","財務證據",{}),"bars":field("bars","歷史行情",[])}
    return {"cash":float(st.number_input("現金部位（NT$）",min_value=0.,key="agent_manager_cash")),"positions":field("positions","持倉與研究證據",[])}
def render(api,personal,is_admin):
    token=st.session_state.get("token") or ""
    if not personal or not is_admin or not token or os.getenv("AGENT_MANAGER_UI_ENABLED")!="1":
        clear();return
    owner=hashlib.sha256(token.encode()).hexdigest()
    key="agent_manager_cache"
    cache=st.session_state.get(key,{})
    if cache.get("owner")!=owner:
        clear();cache={"owner":owner}
    st.session_state[key]=cache
    with st.expander("AI Agent 管理中心"):
        st.caption("Shadow Mode｜僅隔離快照分析")
        if st.button("查詢 Agent 狀態",key="agent_manager_overview"):
            cache.clear();cache["owner"]=owner
            cache["overview"]=api("GET","/admin/agents/overview")
            cache["at"]=time.monotonic()
        overview=cache.get("overview")
        if not overview or time.monotonic()-cache.get("at",0)>60:
            cache.pop("report",None);return
        st.dataframe(overview["agents"])
        if st.button("查詢執行與審核紀錄",key="agent_manager_history"):
            st.json(api("GET","/admin/agents/history"))
        names=[a["name"] for a in overview["agents"] if a["enabled"] and a["registered"]]
        if not names:return
        name=st.selectbox("Agent",names,format_func=lambda n:LABELS[n],key="agent_manager_select")
        active=st.checkbox("啟用本次分析",key="agent_manager_enable_"+name)
        try:
            payload=snapshot(name)
            digest=hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()
        except (ValueError,TypeError):
            cache.pop("report",None);st.warning("快照格式錯誤");return
        report=cache.get("report")
        if not active or not report or report[:2]!=(name,digest) or time.monotonic()-report[2]>=60:
            cache.pop("report",None)
        if st.button("分析",disabled=not active,key="agent_manager_run") and not cache.get("report"):
            cache.pop("report",None)
            result=api("POST","/admin/agents/run/"+name,json=payload)
            if result:cache["report"]=(name,digest,time.monotonic(),result)
        if active and cache.get("report"):
            result=cache["report"][3];r=result.get("report",{})
            st.caption("狀態："+str(r.get("status",result.get("status","unknown"))))
            if name=="risk" and isinstance(r.get("weights"),dict):st.bar_chart(r["weights"])
            if name=="data_auditor" and isinstance(r.get("rows"),list):st.dataframe(r["rows"])
            if name=="notification" and isinstance(r.get("rows"),list):st.dataframe(r["rows"])
            if name=="recovery" and isinstance(r.get("plans"),list):st.dataframe(r["plans"])
            if name=="research" and isinstance(r.get("factors"),dict):st.json(r["factors"])
            if name=="recovery" and result.get("review_id") and r.get("plans"):
                plan=st.selectbox("模擬審核項目",r["plans"],format_func=lambda p:p["category"],key="agent_manager_plan")
                event=st.selectbox("審核動作",["approve","reject","revoke"],key="agent_manager_event")
                if st.button("提交模擬審核",key="agent_manager_review"):
                    st.json(api("POST","/admin/agents/review",json={"review_id":result["review_id"],"plan":plan["id"],"version":plan["evidence_version"],"event":event,"operation_id":uuid.uuid4().hex}))
            st.json(result)
