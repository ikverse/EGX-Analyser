import os
import httpx
import pandas as pd
import streamlit as st

st.set_page_config(page_title="EGX Intelligence", page_icon="📈", layout="wide")
st.markdown("<style>.stApp { background:#111827; color:#f9fafb; }</style>", unsafe_allow_html=True)
api_url = os.getenv("API_URL", "http://localhost:8000")


def api(path: str, method: str = "GET", json: dict | None = None):
    return httpx.request(method, f"{api_url}{path}", json=json, timeout=10).json()


page = st.sidebar.radio("Navigate", ["Dashboard", "Channels", "Stocks", "Recommendations", "Reports", "Analytics", "Search", "Settings"])
st.title(f"EGX Intelligence · {page}")
if page == "Dashboard":
    data = api("/analytics/consensus")
    st.metric("Stocks with consensus", len(data))
    st.dataframe(pd.DataFrame(data), use_container_width=True)
elif page == "Search":
    query = st.text_input("Ask about the market")
    if query: st.dataframe(pd.DataFrame(api("/search", "POST", {"query": query})), use_container_width=True)
elif page == "Reports":
    if st.button("Generate daily report"): st.json(api("/reports/daily", "POST"))
    st.dataframe(pd.DataFrame(api("/reports")), use_container_width=True)
elif page == "Settings":
    st.subheader("Telegram channels")
    channel_handle = st.text_input("Channel username", placeholder="e.g. EGXSignals (without @)")
    channel_title = st.text_input("Display name (optional)")
    if st.button("Add channel") and channel_handle:
        st.json(api("/channels", "POST", {"handle": channel_handle, "title": channel_title or None}))
    for channel in api("/channels"):
        left, right = st.columns([4, 1])
        left.write(f"@{channel['handle']}")
        enabled = right.toggle("Active", value=channel.get("active", True), key=f"channel-{channel['id']}")
        if enabled != channel.get("active", True):
            api(f"/channels/{channel['id']}", "PATCH", {"active": enabled})
            st.rerun()
else:
    routes = {"Channels": "/channels", "Stocks": "/stocks", "Recommendations": "/recommendations", "Analytics": "/analytics/consensus"}
    st.dataframe(pd.DataFrame(api(routes[page])), use_container_width=True)
