"""Northstar Assist monitoring dashboard.

Sources: local red-team results (``results/*.jsonl``, offline default) or the Bedrock model-invocation log
group via CloudWatch Logs Insights. All aggregation is delegated to ``tools/metrics.py`` through
``monitoring_data``; this file only handles layout and source selection.
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # streamlit_app/, for `monitoring_data`

import monitoring_data as md  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional for this page
    pass

st.set_page_config(page_title="Northstar Assist – Monitoring", page_icon="⭐", layout="wide")

SOURCE_LOCAL = "Local results (offline)"
SOURCE_CLOUDWATCH = "CloudWatch Logs Insights"
CACHE_TTL_SECONDS = 60
PRIVACY_NOTE = ("Prompt text is never shown beyond 80 characters, and the CloudWatch view shows guardrail "
                "policies instead of prompts: invocation logs can contain employee and customer PII.")

settings = md.settings_from_env(os.environ)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Querying CloudWatch Logs Insights...")
def fetch_cloudwatch(region: str, log_group: str, role_name: str, window_seconds: int, minute_bucket: int):
    """Cached per minute; ``minute_bucket`` keeps the window anchored while the cache is warm."""
    client = md.make_logs_client(region)
    now = datetime.fromtimestamp(minute_bucket * 60, tz=timezone.utc)
    return md.fetch_invocation_records(client, log_group, role_name, timedelta(seconds=window_seconds), now=now)


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


# ----------------------------------------------------------------------------- sidebar
st.sidebar.header("Data source")
source = st.sidebar.radio("Source", [SOURCE_LOCAL, SOURCE_CLOUDWATCH], label_visibility="collapsed")
window_options = list(md.WINDOWS) if source == SOURCE_LOCAL else [w for w in md.WINDOWS if md.WINDOWS[w]]
default_window = "All time" if source == SOURCE_LOCAL else "Last 24 hours"
window_name = st.sidebar.selectbox("Time window", window_options, index=window_options.index(default_window))
window = md.WINDOWS[window_name]
now = datetime.now(timezone.utc)
since = now - window if window else None

result_files = md.list_result_files(settings.results_dir)
# Always offered: local files are also the fallback when CloudWatch is unavailable.
selected_files: list[Path] = st.sidebar.multiselect(
    "Result files", result_files, default=result_files[:1], format_func=lambda p: p.name,
    help="Defaults to the newest run. Select several to combine runs.")
if source == SOURCE_CLOUDWATCH:
    st.sidebar.caption(f"Log group: `{settings.log_group}`  \nRole filter: `{settings.role_name}`  \n"
                       f"Region: `{settings.region}`")
st.sidebar.caption(PRIVACY_NOTE)

# ------------------------------------------------------------------------------- data
st.title("Northstar Assist – Monitoring")
st.caption("Guardrail interventions, retrieval health and token usage for the Northstar Assist harness.")

dashboard = None
if source == SOURCE_CLOUDWATCH:
    try:
        records, truncated = fetch_cloudwatch(settings.region, settings.log_group, settings.role_name,
                                              int(window.total_seconds()), int(time.time() // 60))
        dashboard = md.build_invocation_dashboard(records)
        if truncated:
            st.warning(f"Result limit of {md.MAX_QUERY_ROWS} log records reached; narrow the time window.")
        if not records:
            st.info("No invocation records matched. Check the log group, the role filter and the time window; the "
                    "`identity.arn` path is unverified until a real log line has been inspected (PLAN R2).")
    except md.SOURCE_ERRORS as exc:
        st.error(f"CloudWatch is unavailable: {exc}. Showing local result files instead.")
    except ValueError as exc:  # invalid HARNESS_ROLE_NAME etc.
        st.error(f"Invalid monitoring configuration: {exc}. Showing local result files instead.")

if dashboard is None:
    if not selected_files:
        st.info("No result files selected or found. Run `tools/run_suite.py` to create `results/suite_*.jsonl`, "
                "or choose the CloudWatch source.")
    try:
        dashboard = md.build_suite_dashboard(md.load_local_records(selected_files, since))
    except (ValueError, OSError) as exc:
        st.error(f"Could not read the selected result files: {exc}")
        st.stop()

# ------------------------------------------------------------------------------- body
source_label = "CloudWatch invocation logs" if dashboard.source == "cloudwatch" else "Local red-team results"
st.subheader(f"{source_label} · {dashboard.record_count} records · {window_name.lower()}")

kpi_cols = st.columns(4)
kpi_cols[0].metric("Guardrail intervention rate", percent(dashboard.intervention_rate))
kpi_cols[1].metric("Retrieval success rate", percent(dashboard.retrieval_success_rate))
kpi_cols[2].metric("p95 output tokens",
                   "n/a" if dashboard.p95_output_tokens is None else f"{dashboard.p95_output_tokens:,.0f}")
kpi_cols[3].metric("Errors", dashboard.error_count)

left, right = st.columns(2)
with left:
    st.markdown(f"#### Interventions by {dashboard.group_label.lower()}")
    if dashboard.interventions_by_group:
        chart = pd.Series(dashboard.interventions_by_group, name="Interventions").sort_values(ascending=False)
        st.bar_chart(chart)
    else:
        st.caption("No guardrail interventions in this view.")
with right:
    st.markdown("#### Tokens over time")
    if dashboard.token_series:
        series = pd.DataFrame(dashboard.token_series).set_index("timestamp")
        st.line_chart(series[["output_tokens", "input_tokens"]].rename(
            columns={"output_tokens": "Output tokens", "input_tokens": "Input tokens"}))
    else:
        st.caption("No token usage with timestamps in this view.")

st.markdown("#### Consistency findings")
if dashboard.consistency:
    st.dataframe(pd.DataFrame(dashboard.consistency).assign(
        outcomes=lambda df: df["outcomes"].map(", ".join)), hide_index=True, width="stretch")
else:
    st.caption(dashboard.notes[0] if dashboard.notes else "No cases with disagreeing runs.")

st.markdown("#### Recent guardrail interventions")
if dashboard.blocked:
    blocked = pd.DataFrame(dashboard.blocked).rename(columns={
        "case_id": "Case / request", "timestamp": "Timestamp", "outcome": "Outcome", "turn": "Turn (first 80 chars)"})
    st.dataframe(blocked, hide_index=True, width="stretch")
else:
    st.caption("No guardrail interventions in this view.")
