import streamlit as st
import httpx
import pandas as pd
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
from typing import Optional

st.set_page_config(
    page_title="Watchdog Monitoring",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

API_BASE_URL = "http://app:8000/api/v1"
API_TIMEOUT = 10.0


class WatchdogAPI:
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {"X-API-Key": api_key} if api_key else {}

    def get_monitors(self):
        """Fetch all monitors"""
        with httpx.Client(timeout=API_TIMEOUT) as client:
            response = client.get(
                f"{self.base_url}/monitors/",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    def get_monitor_stats(self, monitor_id: int, hours: int = 24):
        """Fetch statistics for specific monitor"""
        with httpx.Client(timeout=API_TIMEOUT) as client:
            response = client.get(
                f"{self.base_url}/monitors/{monitor_id}/stats",
                params={"hours": hours},
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()


def render_sidebar():
    with st.sidebar:
        st.title("🛡️ Watchdog")
        st.markdown("---")

        api_key = st.text_input(
            "API Key",
            type="password",
            help="Enter your API key to access monitoring data"
        )

        time_range = st.selectbox(
            "Time Range",
            options=[1, 6, 12, 24, 48, 72, 168],
            index=3,
            format_func=lambda x: f"Last {x} hours"
        )

        if st.button("🔄 Refresh Data", use_container_width=True):
            st.rerun()

        st.markdown("---")

        st.markdown("### 🔗 Quick Links")
        st.markdown("[📚 API Swagger Docs](/docs)")
        st.markdown("[🔄 API ReDoc](/redoc)")
        
        st.markdown("---")
        st.caption("v1.1.2 | Powered by FastAPI + Streamlit")

        return api_key, time_range


def render_monitor_card(monitor: dict):
    status = monitor.get("last_check_status")

    if status is None:
        status_icon = "⏸️"
        status_text = "Pending"
        status_color = "gray"
    elif status:
        status_icon = "✅"
        status_text = "Healthy"
        status_color = "green"
    else:
        status_icon = "❌"
        status_text = "Down"
        status_color = "red"

    with st.container():
        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            st.markdown(f"### {status_icon} {monitor.get('name', 'Unnamed')}")
            st.caption(monitor.get('url', 'No URL'))

        with col2:
            st.metric("Status", status_text)

        with col3:
            st.metric("Interval", f"{monitor.get('interval', 0)}s")


def render_latency_chart(data: list):
    if not data:
        st.info("No data available")
        return

    df = pd.DataFrame(data)
    df['start_time'] = pd.to_datetime(df['start_time'])
    
    fig = go.Figure()

    success_df = df[df['is_success'] == True]
    fig.add_trace(go.Scatter(
        x=success_df['start_time'],
        y=success_df['duration_ms'],
        mode='lines+markers',
        name='Latency (success)',
        line=dict(color='green', width=2),
        marker=dict(size=6)
    ))

    failed_df = df[df['is_success'] == False]
    if not failed_df.empty:
        fig.add_trace(go.Scatter(
            x=failed_df['start_time'],
            y=failed_df['duration_ms'],
            mode='markers',
            name='Failed checks',
            marker=dict(color='red', size=10, symbol='x')
        ))

    fig.update_layout(
        title="Response Time Timeline",
        xaxis_title="Time",
        yaxis_title="Latency (ms)",
        hovermode='x unified',
        height=400
    )

    st.plotly_chart(fig, use_container_width=True)


def render_uptime_stats(data: list):
    if not data:
        st.info("No data available")
        return

    df = pd.DataFrame(data)
    total_checks = len(df)
    successful_checks = df['is_success'].sum()
    uptime_percentage = (successful_checks / total_checks * 100) if total_checks > 0 else 0

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Uptime", f"{uptime_percentage:.2f}%")

    with col2:
        st.metric("Total Checks", total_checks)

    with col3:
        avg_latency = df[df['is_success']]['duration_ms'].mean()
        st.metric("Avg Latency", f"{avg_latency:.0f}ms" if pd.notna(avg_latency) else "N/A")

    with col4:
        failed_checks = total_checks - successful_checks
        st.metric("Failed Checks", failed_checks)


def main():
    api_key, time_range = render_sidebar()

    st.title("📊 Monitoring Dashboard")
    st.caption("Real-time visualization of your monitors. Manage monitors via [Swagger UI](/docs)")

    if not api_key:
        st.warning("⚠️ Please enter your API key in the sidebar to access monitoring data")
        st.info("""
        **How to get your API key:**
        1. Open [API Swagger](/docs)
        2. Create a user or login
        3. Copy your API key from your profile
        """)
        return

    api = WatchdogAPI(API_BASE_URL, api_key)

    try:
        with st.spinner("Loading monitors..."):
            monitors = api.get_monitors()

        if not monitors:
            st.info("📭 No monitors configured yet.")
            st.markdown("**Add monitors via [Swagger API](/docs)** - navigate to `/monitors/add-urls` endpoint")
            return

        st.subheader(f"Active Monitors ({len(monitors)})")

        for monitor in monitors:
            try:
                monitor_name = str(monitor.get('name', 'Unnamed'))
                monitor_url = str(monitor.get('url', 'No URL'))
                expander_label = f"{monitor_name} - {monitor_url}"
            except (UnicodeEncodeError, UnicodeDecodeError):
                expander_label = f"Monitor ID: {monitor.get('id', 'Unknown')}"
            
            with st.expander(expander_label, expanded=False):
                render_monitor_card(monitor)

                try:
                    with st.spinner(f"Loading stats..."):
                        stats = api.get_monitor_stats(monitor['id'], hours=time_range)

                    st.markdown("#### Statistics")
                    render_uptime_stats(stats)

                    st.markdown("#### Performance")
                    render_latency_chart(stats)

                except httpx.HTTPError as e:
                    st.warning(f"⚠️ Could not load statistics: {str(e)}")
                except Exception as e:
                    st.error(f"❌ Error loading stats: {str(e)}")
        
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            st.error("❌ Invalid API key. Please check your credentials.")
        elif e.response.status_code == 403:
            st.error("❌ Access forbidden. Check your API key permissions.")
        else:
            st.error(f"❌ API Error: {e.response.status_code}")
            with st.expander("Error Details"):
                st.code(e.response.text)
    except httpx.ConnectError:
        st.error("❌ Cannot connect to API backend. Check if the service is running.")
    except Exception as e:
        st.error(f"❌ Unexpected error: {str(e)}")
        with st.expander("Full Error"):
            st.exception(e)


if __name__ == "__main__":
    main()
