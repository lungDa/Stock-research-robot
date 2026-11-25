"""Session-local operator surface, no automatic analysis."""
import os,json,time,hashlib
import streamlit as st
def render(api,personal,is_admin):
    key="agent_manager_cache"
    if not personal or not is_admin or os.getenv("AGENT_MANAGER_UI_ENABLED")!="1":
        st.session_state.pop(key,None)
        return
    owner=hashlib.sha256(st.session_state.get("token","").encode()).hexdigest()
    cache=st.session_state.get(key,{})
    if cache.get("owner")!=owner:cache={"owner":owner}
    st.session_state[key]=cache
    with st.expander("AI Agent 管理中心"):
        st.caption("Shadow Mode｜僅隔離快照分析，不執行正式操作")
        if st.button("查詢 Agent 狀態",key="agent_overview"):
            cache["overview"]=api("GET","/admin/agents/overview")
            cache.pop("report",None)
        overview=cache.get("overview")
        if not overview:return
        st.dataframe(overview["agents"])
        names=[a["name"] for a in overview["agents"] if a["enabled"]]
        if not names:return
        name=st.selectbox("Agent",names,key="agent_select")
        active=st.checkbox("啟用本次快照分析",key="agent_local_enable")
        raw=st.text_area("隔離 JSON 快照",key="agent_snapshot",max_chars=200000)
        if st.button("分析",disabled=not active,key="agent_run"):
            cache.pop("report",None)
            try:
                payload=json.loads(raw)
                if not isinstance(payload,dict):raise ValueError()
                result=api("POST","/admin/agents/run/"+name,json=payload)
                if result:cache["report"]=(name,time.monotonic(),result)
            except ValueError:st.error("快照格式錯誤")
        report=cache.get("report")
        if active and report and report[0]==name and time.monotonic()-report[1]<60:
            st.json(report[2])
