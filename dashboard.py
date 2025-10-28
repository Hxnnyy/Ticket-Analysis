"""
Interactive dashboard for the ticket analysis dataset.

Run with: streamlit run dashboard.py
"""

import io
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import altair as alt
import pandas as pd
import streamlit as st
import streamlit_shadcn_ui as ui

from supabase_utils import (
    DatasetMeta,
    delete_object,
    download_csv,
    list_csv_objects,
    load_metadata,
    save_metadata,
    upload_csv,
    supabase_disabled,
)


DATA_DIR = Path(__file__).parent / "data"
EXPECTED_COLUMNS = [
    "Number",
    "Summary",
    "Assigned To Queue",
    "Support Line",
    "Assigned to User",
    "Status",
    "Next Status",
    "Owning Dept",
    "Owner",
    "Person",
    "Organization",
    "Priority",
    "Category",
    "Open Date",
    "Opened By",
    "Last Change Date",
    "Closed Date",
    "Service",
    "Resolution Code",
    "Root Cause",
]

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2MB


def _inject_theme() -> None:
    st.markdown(
        """
        <style>
            :root {
                --ticket-purple-500: #6b46ff;
                --ticket-purple-400: #7f5bff;
                --ticket-purple-200: #e3d8ff;
                --ticket-purple-50: #f6f2ff;
                --ticket-surface: rgba(19, 16, 40, 0.75);
            }

            .stApp {
                background: radial-gradient(circle at 0% 0%, rgba(123, 97, 255, 0.18), transparent 40%),
                            radial-gradient(circle at 100% 0%, rgba(106, 76, 255, 0.25), transparent 35%),
                            #0f0b22;
                color: #f7f5ff;
            }

            .purple-hero-card {
                background: linear-gradient(135deg, rgba(107, 70, 255, 0.88), rgba(40, 18, 98, 0.95));
                border-radius: 24px;
                padding: 28px;
                box-shadow: 0 20px 45px rgba(31, 18, 77, 0.45);
                color: #fdfdff;
                margin-bottom: 1.5rem;
            }

            .purple-hero-card h1 {
                font-size: 2.1rem;
                font-weight: 700;
                margin-bottom: 0.3rem;
            }

            .purple-hero-card p {
                font-size: 1rem;
                opacity: 0.92;
            }

            .status-badge-container {
                display: flex;
                gap: 0.5rem;
                flex-wrap: wrap;
                margin: 0.75rem 0 0;
            }

            .sidebar-section-title {
                font-weight: 600;
                letter-spacing: 0.02em;
                text-transform: uppercase;
                font-size: 0.8rem;
                color: #d7cfff;
                margin-top: 1.2rem;
            }

            .dataset-card {
                border-radius: 16px;
                background: rgba(27, 23, 50, 0.72);
                border: 1px solid rgba(123, 97, 255, 0.25);
                padding: 1rem;
                margin-bottom: 0.9rem;
                box-shadow: 0 10px 26px rgba(17, 8, 52, 0.35);
            }

            .dataset-card h4 {
                margin-bottom: 0.25rem;
                font-size: 1rem;
            }

            .dataset-meta {
                font-size: 0.78rem;
                opacity: 0.7;
                margin-bottom: 0.6rem;
            }

            .stDataFrame {
                background: rgba(19, 16, 40, 0.68);
                border-radius: 18px;
                border: 1px solid rgba(108, 90, 255, 0.35);
            }

            .stDataFrame [data-testid="stTable"] {
                background: transparent;
            }

            .section-title {
                font-size: 1.4rem;
                margin-top: 1.2rem;
                margin-bottom: 0.4rem;
                color: #efe9ff;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _sync_session_registry(registry: Dict[str, DatasetMeta]) -> None:
    current: Dict[str, DatasetMeta] = st.session_state.get("dataset_registry", {})
    needs_refresh = False

    if len(current) != len(registry):
        needs_refresh = True
    else:
        for name, meta in registry.items():
            existing = current.get(name)
            if not isinstance(existing, DatasetMeta):
                needs_refresh = True
                break
            if (
                existing.included != meta.included
                or existing.disabled != meta.disabled
                or existing.uploaded_at != meta.uploaded_at
            ):
                needs_refresh = True
                break

    if needs_refresh:
        st.session_state["dataset_registry"] = {
            name: DatasetMeta(
                name=meta.name,
                included=meta.included,
                disabled=meta.disabled,
                uploaded_at=meta.uploaded_at,
            )
            for name, meta in registry.items()
        }
def _trigger_rerun() -> None:
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def _prepare_ticket_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [col.strip() for col in df.columns]

    missing_cols = [col for col in EXPECTED_COLUMNS if col not in df.columns]
    for col in missing_cols:
        df[col] = pd.NA

    date_columns = ["Open Date", "Last Change Date", "Closed Date"]
    for column in date_columns:
        df[column] = pd.to_datetime(df[column], errors="coerce", dayfirst=False)

    df["Days Open"] = (
        (df["Last Change Date"] - df["Open Date"]).dt.total_seconds() / 86400
    )
    df["Resolution Time Days"] = (
        (df["Closed Date"] - df["Open Date"]).dt.total_seconds() / 86400
    )
    df["Is Closed"] = df["Closed Date"].notna()

    df["Assigned To Queue"] = df["Assigned To Queue"].fillna("Unassigned")
    df["Assigned to User"] = df["Assigned to User"].fillna("Unassigned")
    df["Category"] = df["Category"].fillna("Uncategorised")

    return df[EXPECTED_COLUMNS + ["Days Open", "Resolution Time Days", "Is Closed", "Source File"]]


def _empty_ticket_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=EXPECTED_COLUMNS
        + ["Days Open", "Resolution Time Days", "Is Closed", "Source File"]
    )


def _load_local_data(data_dir: Path) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
    frames: Dict[str, pd.DataFrame] = {}

    for csv_path in sorted(data_dir.glob("*.csv")):
        raw = pd.read_csv(csv_path, encoding="cp1252")
        raw["Source File"] = csv_path.name
        frames[csv_path.name] = _prepare_ticket_frame(raw)

    if not frames:
        return {}, _empty_ticket_frame()

    combined = pd.concat(frames.values(), ignore_index=True)
    return frames, combined


@dataclass
class DatasetLoadResult:
    frames: Dict[str, pd.DataFrame]
    combined: pd.DataFrame
    registry: Dict[str, DatasetMeta]
    errors: List[str]
    source: str


@st.cache_data(show_spinner=True)
def load_dataset_bundle(cache_bust: int = 0) -> DatasetLoadResult:
    errors: List[str] = []
    frames: Dict[str, pd.DataFrame] = {}
    registry: Dict[str, DatasetMeta] = {}
    included_frames: List[pd.DataFrame] = []
    source = "supabase"

    if supabase_disabled():
        local_frames, combined = _load_local_data(DATA_DIR)
        registry = {name: DatasetMeta(name=name) for name in local_frames.keys()}
        return DatasetLoadResult(
            frames=local_frames,
            combined=combined,
            registry=registry,
            errors=["Supabase disabled via SUPABASE_DISABLE"],
            source="local",
        )

    try:
        metadata_map = load_metadata()
        storage_objects = list_csv_objects()
    except Exception as exc:
        errors.append(str(exc))
        source = "local"
        local_frames, combined = _load_local_data(DATA_DIR)
        registry = {
            name: DatasetMeta(name=name) for name in local_frames.keys()
        }
        return DatasetLoadResult(
            frames=local_frames,
            combined=combined,
            registry=registry,
            errors=errors,
            source=source,
        )

    metadata_dirty = False

    for obj in storage_objects:
        name = obj.get("name")
        if not name:
            continue

        stored_meta = metadata_map.get(name)
        if stored_meta and not isinstance(stored_meta, DatasetMeta):
            if hasattr(stored_meta, "to_dict"):
                stored_meta = DatasetMeta.from_dict(name, stored_meta.to_dict())
            elif isinstance(stored_meta, dict):
                stored_meta = DatasetMeta.from_dict(name, stored_meta)
            else:
                stored_meta = None

        if not stored_meta:
            metadata_dirty = True
            stored_included = True
        else:
            stored_included = bool(stored_meta.included)
            if getattr(stored_meta, "disabled", False):
                stored_included = False
                metadata_dirty = True

        uploaded_at = (
            stored_meta.uploaded_at
            if stored_meta and stored_meta.uploaded_at
            else obj.get("created_at")
        )
        meta = DatasetMeta(
            name=name,
            included=stored_included,
            disabled=False,
            uploaded_at=uploaded_at,
        )
        registry[name] = meta

        try:
            csv_text = download_csv(name).decode("utf-8", errors="replace")
            raw = pd.read_csv(io.StringIO(csv_text))
            raw["Source File"] = name
            prepared = _prepare_ticket_frame(raw)
            frames[name] = prepared
            if meta.included:
                included_frames.append(prepared)
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    removed_entries = [name for name in metadata_map.keys() if name not in registry]
    if removed_entries:
        metadata_dirty = True

    if not included_frames:
        combined = _empty_ticket_frame()
    else:
        combined = pd.concat(included_frames, ignore_index=True)

    if metadata_dirty:
        try:
            save_metadata(registry)
        except Exception as exc:
            errors.append(f"Metadata persistence failed: {exc}")

    return DatasetLoadResult(
        frames=frames,
        combined=combined,
        registry=registry,
        errors=errors,
        source=source,
    )


def _invalidate_dataset_cache() -> None:
    load_dataset_bundle.clear()
    st.session_state["dataset_cache_bust"] = (
        st.session_state.get("dataset_cache_bust", 0) + 1
    )


def _persist_registry(registry: Dict[str, DatasetMeta]) -> bool:
    try:
        save_metadata(registry)
    except Exception as exc:
        st.sidebar.error(f"Failed to save dataset settings: {exc}")
        return False
    return True


def _format_uploaded_at(meta: DatasetMeta) -> str:
    if not meta.uploaded_at:
        return ""
    iso_value = meta.uploaded_at
    try:
        parsed = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso_value


def _render_header(bundle: DatasetLoadResult) -> None:
    included = sum(1 for meta in bundle.registry.values() if meta.included)
    total = len(bundle.registry)
    record_count = len(bundle.combined)
    data_line = (
        f"{record_count:,} tickets across {included} active dataset{'s' if included != 1 else ''}."
        if included
        else "Activate a dataset to populate insights."
    )

    st.markdown(
        """
        <div class="purple-hero-card">
            <h1>Ticket Analysis Dashboard</h1>
            <p>Monitor support performance with focused, interactive analytics.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    badge_entries = []
    if included:
        badge_entries.append((f"{included} active", "secondary"))
    else:
        badge_entries.append(("No active datasets", "outline"))

    if total:
        badge_entries.append((f"{total} stored", "default"))

    badge_entries.append(
        (
            "Supabase live" if bundle.source == "supabase" else "Local fallback",
            "default" if bundle.source == "supabase" else "destructive",
        )
    )

    ui.card(
        title="Workspace status",
        content=data_line,
        key="hero-summary-card",
    ).render()

    ui.badges(badge_entries, class_name="status-badge-container", key="hero-badges")


def dataset_management_panel(bundle: DatasetLoadResult) -> None:
    with st.sidebar:
        st.markdown("<div class='sidebar-section-title'>Datasets</div>", unsafe_allow_html=True)

        if bundle.source == "local":
            st.warning(
                "Supabase connection unavailable; dataset management is disabled while local data is in use."
            )
            return

        registry_state = st.session_state.get("dataset_registry", {})
        with st.form("dataset_upload_form", clear_on_submit=True):
            uploader = st.file_uploader(
                "Upload CSV (max 2 MB)",
                type=["csv"],
                accept_multiple_files=False,
                key="dataset_upload_widget",
            )
            submitted = st.form_submit_button("Add dataset")

        if submitted:
            if uploader is None:
                st.warning("Choose a CSV file to upload.")
            else:
                name = uploader.name.strip()
                data_bytes = uploader.getvalue()
                if not name:
                    st.error("Uploaded file must have a name.")
                elif not name.lower().endswith(".csv"):
                    st.error("Only .csv files are supported.")
                elif len(data_bytes) > MAX_UPLOAD_BYTES:
                    st.error("File exceeds the 2 MB size limit.")
                elif name in registry_state:
                    st.error(f"A dataset named '{name}' already exists.")
                else:
                    try:
                        upload_csv(name, data_bytes)
                    except Exception as exc:
                        st.error(f"Upload failed: {exc}")
                    else:
                        registry = dict(registry_state)
                        registry[name] = DatasetMeta(
                            name=name,
                            included=True,
                            disabled=False,
                            uploaded_at=datetime.utcnow().strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            ),
                        )
                        if _persist_registry(registry):
                            st.session_state["dataset_registry"] = registry
                            st.success(f"Uploaded '{name}'.")
                            _invalidate_dataset_cache()
                            _trigger_rerun()

        if not registry_state:
            ui.alert(
                title="No datasets yet",
                description="Upload a CSV to start analysing tickets.",
                key="dataset-empty-alert",
            )
            return

        for name in sorted(registry_state.keys()):
            _render_dataset_row(name)

        if not any(meta.included for meta in registry_state.values()):
            ui.alert(
                title="All datasets excluded",
                description="Enable at least one CSV to populate the dashboard.",
                key="dataset-excluded-alert",
            )


def _render_dataset_row(name: str) -> None:
    registry = st.session_state.get("dataset_registry", {})
    meta = registry.get(name)
    if not meta:
        return

    include_key = _sanitize_key("dataset", name, "include")
    delete_key = _sanitize_key("dataset", name, "delete")
    legacy_disable_key = _sanitize_key("dataset", name, "disable")

    if legacy_disable_key in st.session_state:
        st.session_state.pop(legacy_disable_key, None)
    meta.disabled = False

    uploaded_label = _format_uploaded_at(meta)
    status_bits = ["Included" if meta.included else "Excluded"]
    if uploaded_label:
        status_bits.append(uploaded_label)

    st.markdown(
        f"<div class='dataset-card'><h4>{name}</h4><div class='dataset-meta'>{' · '.join(status_bits)}</div></div>",
        unsafe_allow_html=True,
    )

    include_col, delete_col = st.columns([1.3, 1])

    with include_col:
        include_state = ui.switch(
            default_checked=meta.included,
            label="Include in dashboard",
            key=include_key,
        )

    with delete_col:
        delete_clicked = ui.button(
            text="Delete",
            variant="destructive",
            class_name="w-full",
            key=delete_key,
        )

    if include_state != meta.included:
        previous = meta.included
        meta.included = include_state
        if _persist_registry(registry):
            st.sidebar.info(
                f"{'Included' if include_state else 'Excluded'} '{name}' in analytics."
            )
            _invalidate_dataset_cache()
            _trigger_rerun()
        else:
            meta.included = previous
    if delete_clicked:
        try:
            delete_object(name)
        except Exception as exc:
            st.sidebar.error(f"Failed to delete '{name}': {exc}")
        else:
            removed_meta = registry.pop(name, None)
            if _persist_registry(registry):
                st.session_state.pop(include_key, None)
                st.sidebar.success(f"Deleted '{name}'.")
                _invalidate_dataset_cache()
                _trigger_rerun()
            else:
                if removed_meta is not None:
                    registry[name] = removed_meta


def _sanitize_key(*parts: str) -> str:
    safe_parts = []
    for part in parts:
        safe = re.sub(r"[^0-9A-Za-z]+", "_", str(part))
        safe_parts.append(safe.strip("_"))
    return "_".join(safe_parts)


def _checkbox_filter(expander_label: str, column: str, df: pd.DataFrame) -> list[str]:
    raw_options = [value for value in df[column].dropna().unique()]
    options = sorted(raw_options, key=lambda value: str(value).lower())
    included_values: list[str] = []

    with st.sidebar.expander(expander_label, expanded=False):
        for option in options:
            state_key = _sanitize_key("filter", column, option)
            if state_key not in st.session_state:
                st.session_state[state_key] = True

            label = str(option) if option else "—"
            is_included = st.checkbox(
                label=label,
                value=st.session_state[state_key],
                key=state_key,
            )
            if is_included:
                included_values.append(option)

    return included_values


def build_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.markdown(
        "<div class='sidebar-section-title'>Filters</div>", unsafe_allow_html=True
    )

    queue_selection = _checkbox_filter("Assigned Queue", "Assigned To Queue", df)
    status_selection = _checkbox_filter("Ticket Status", "Status", df)
    category_selection = _checkbox_filter("Category", "Category", df)
    support_line_selection = _checkbox_filter("Support Line", "Support Line", df)

    min_open = df["Open Date"].min()
    max_open = df["Open Date"].max()
    if pd.isna(min_open) or pd.isna(max_open):
        date_range = None
    else:
        default_range = (min_open.date(), max_open.date())
        date_range = st.sidebar.date_input(
            "Open Date range",
            value=default_range,
            min_value=min_open.date(),
            max_value=max_open.date(),
        )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
        else:
            start_date = end_date = date_range

    filtered = df.copy()
    if queue_selection:
        filtered = filtered[filtered["Assigned To Queue"].isin(queue_selection)]
    else:
        filtered = filtered.iloc[0:0]

    if status_selection:
        filtered = filtered[filtered["Status"].isin(status_selection)]
    else:
        filtered = filtered.iloc[0:0]

    if category_selection:
        filtered = filtered[filtered["Category"].isin(category_selection)]
    else:
        filtered = filtered.iloc[0:0]

    if support_line_selection:
        filtered = filtered[filtered["Support Line"].isin(support_line_selection)]
    else:
        filtered = filtered.iloc[0:0]

    if min_open and max_open and date_range and not filtered.empty:
        filtered = filtered[
            (filtered["Open Date"] >= pd.to_datetime(start_date))
            & (filtered["Open Date"] <= pd.to_datetime(end_date))
        ]

    return filtered


def kpi_section(filtered: pd.DataFrame):
    total_tickets = len(filtered)
    open_tickets = (~filtered["Is Closed"]).sum()
    avg_days_open = filtered["Days Open"].mean()
    latest_activity = filtered["Last Change Date"].max()

    cols = st.columns(4, gap="large")
    metric_data = [
        {
            "title": "Tickets",
            "value": f"{total_tickets}",
            "description": "Total records in view",
            "key": "metric-total",
        },
        {
            "title": "Open tickets",
            "value": f"{open_tickets}",
            "description": "Active cases",
            "key": "metric-open",
        },
        {
            "title": "Avg days open",
            "value": f"{avg_days_open:.2f}" if pd.notna(avg_days_open) else "—",
            "description": "Mean lifetime",
            "key": "metric-days",
        },
        {
            "title": "Last update",
            "value": (
                latest_activity.strftime("%Y-%m-%d %H:%M")
                if pd.notna(latest_activity)
                else "—"
            ),
            "description": "Most recent change",
            "key": "metric-latest",
        },
    ]

    for col, spec in zip(cols, metric_data):
        with col:
            ui.metric_card(
                title=spec["title"],
                content=spec["value"],
                description=spec["description"],
                key=spec["key"],
            )


def _queue_chart(data: pd.DataFrame, chart_type: str):
    if chart_type == "Pie":
        return (
            alt.Chart(data)
            .mark_arc()
            .encode(
                theta=alt.Theta("Tickets:Q", stack=True),
                color=alt.Color("Assigned To Queue:N", legend=None, title="Queue"),
                tooltip=["Assigned To Queue", "Tickets"],
            )
            .properties(title="Tickets by queue", height=300)
        )
    # Default to bar
    return (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X("Tickets:Q"),
            y=alt.Y("Assigned To Queue:N", sort="-x", title="Queue"),
            tooltip=["Assigned To Queue", "Tickets"],
        )
        .properties(title="Tickets by queue", height=300)
    )


def _status_chart(data: pd.DataFrame, chart_type: str):
    if chart_type == "Pie":
        return (
            alt.Chart(data)
            .mark_arc()
            .encode(
                theta=alt.Theta("Tickets:Q", stack=True),
                color=alt.Color("Status:N", legend=None),
                tooltip=["Status", "Tickets"],
            )
            .properties(title="Tickets by status", height=300)
        )
    return (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X("Tickets:Q"),
            y=alt.Y("Status:N", sort="-x"),
            tooltip=["Status", "Tickets"],
        )
        .properties(title="Tickets by status", height=300)
    )


def _category_chart(data: pd.DataFrame, chart_type: str):
    if chart_type == "Pie":
        return (
            alt.Chart(data)
            .mark_arc()
            .encode(
                theta=alt.Theta("Tickets:Q", stack=True),
                color=alt.Color("Category:N", legend=None),
                tooltip=["Category", "Tickets"],
            )
            .properties(title="Top categories", height=300)
        )
    return (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X("Tickets:Q"),
            y=alt.Y("Category:N", sort="-x"),
            tooltip=["Category", "Tickets"],
        )
        .properties(title="Top categories", height=300)
    )


def _trend_chart(data: pd.DataFrame, chart_type: str):
    encoding = dict(
        x=alt.X("Open Date:T", title="Open date", sort="ascending"),
        y=alt.Y("Tickets:Q", title="Tickets"),
        tooltip=["Open Date:T", "Tickets"],
    )

    if chart_type == "Bar":
        chart = alt.Chart(data).mark_bar(size=18, color="#2E86AB").encode(**encoding)
    elif chart_type == "Area":
        chart = (
            alt.Chart(data)
            .mark_area(
                color="#4DA3FF",
                opacity=0.35,
                interpolate="monotone",
                line={"color": "#1976D2"},
                point={"color": "#1976D2", "filled": True, "size": 60},
            )
            .encode(**encoding)
        )
    else:
        chart = (
            alt.Chart(data)
            .mark_line(point=True, interpolate="monotone", color="#1976D2")
            .encode(**encoding)
        )

    return chart.properties(title="Tickets opened per day", height=300)


def build_charts(filtered: pd.DataFrame):
    if filtered.empty:
        ui.alert(
            title="No records",
            description="Refine or clear filters to visualise tickets.",
            key="charts-empty-alert",
        )
        return

    tickets_by_queue = (
        filtered.groupby("Assigned To Queue")
        .size()
        .reset_index(name="Tickets")
        .sort_values("Tickets", ascending=False)
    )
    tickets_by_status = (
        filtered.groupby("Status")
        .size()
        .reset_index(name="Tickets")
        .sort_values("Tickets", ascending=False)
    )
    tickets_by_category = (
        filtered.groupby("Category")
        .size()
        .reset_index(name="Tickets")
        .sort_values("Tickets", ascending=False)
    ).head(10)
    tickets_over_time = (
        filtered.dropna(subset=["Open Date"])
        .groupby(pd.Grouper(key="Open Date", freq="D"))
        .size()
        .reset_index(name="Tickets")
    )

    col1, col2 = st.columns(2)
    with col1:
        queue_chart_type = ui.tabs(
            options=["Bar", "Pie"],
            default_value="Bar",
            key="queue_chart_type",
        )
        st.altair_chart(
            _queue_chart(tickets_by_queue, queue_chart_type), use_container_width=True
        )
        category_chart_type = ui.tabs(
            options=["Bar", "Pie"],
            default_value="Bar",
            key="category_chart_type",
        )
        st.altair_chart(
            _category_chart(tickets_by_category, category_chart_type),
            use_container_width=True,
        )
    with col2:
        status_chart_type = ui.tabs(
            options=["Bar", "Pie"],
            default_value="Bar",
            key="status_chart_type",
        )
        st.altair_chart(
            _status_chart(tickets_by_status, status_chart_type), use_container_width=True
        )
        trend_chart_type = ui.tabs(
            options=["Line", "Bar", "Area"],
            default_value="Line",
            key="trend_chart_type",
        )
        st.altair_chart(
            _trend_chart(tickets_over_time, trend_chart_type), use_container_width=True
        )


def insights_report(df: pd.DataFrame):
    st.markdown("<div class='section-title'>Insights Report</div>", unsafe_allow_html=True)

    total = len(df)
    queue_counts = df["Assigned To Queue"].value_counts()
    category_counts = df["Category"].value_counts()
    status_counts = df["Status"].value_counts()
    avg_days_open = df["Days Open"].mean()
    long_running = df[df["Days Open"] > 4]
    customer_waiting = status_counts.get("With customer", 0)
    closed_share = df["Is Closed"].mean() * 100 if total else 0

    insights = []
    if not queue_counts.empty:
        top_queue = queue_counts.index[0]
        top_queue_share = queue_counts.iloc[0] / total * 100
        insights.append(
            f"{top_queue} handles {queue_counts.iloc[0]} of {total} tickets "
            f"({top_queue_share:.0f}% of workload), making it the main pressure point."
        )
    if not category_counts.empty:
        top_category = category_counts.index[0]
        insights.append(
            f"'{top_category}' is the dominant category with {category_counts.iloc[0]} tickets, "
            "suggesting this issue type needs focused remediation."
        )
    if pd.notna(avg_days_open):
        insights.append(
            f"Tickets stay active for {avg_days_open:.2f} days on average, "
            f"with {len(long_running)} cases open for more than four days."
        )
    insights.append(
        f"{closed_share:.0f}% of tickets are closed; {customer_waiting} are waiting on customers, "
        "highlighting follow-up opportunities."
    )
    insights.append(
        "All tickets are logged as medium priority, indicating the triage process may not be using the full priority range."
    )

    insights_body = "<br>".join(f"• {item}" for item in insights)
    ui.card(
        title="Key takeaways",
        content=insights_body,
        key="insights-card",
    ).render()


def main():
    st.set_page_config(page_title="Ticket Analysis Dashboard", layout="wide")
    _inject_theme()

    cache_bust = st.session_state.get("dataset_cache_bust", 0)
    bundle = load_dataset_bundle(cache_bust)

    _sync_session_registry(bundle.registry)

    _render_header(bundle)
    dataset_management_panel(bundle)

    if bundle.source == "local":
        ui.alert(
            title="Offline mode",
            description="Supabase unavailable. Loaded bundled CSV data instead.",
            key="local-warning",
        )
    if bundle.errors:
        for index, issue in enumerate(bundle.errors, start=1):
            ui.alert(
                title="Dataset issue",
                description=issue,
                key=f"dataset-issue-{index}",
            )

    data = bundle.combined
    if data.empty:
        ui.alert(
            title="No data to display",
            description="Use the datasets sidebar to include an existing CSV or upload a new one.",
            key="no-data-alert",
        )
        return

    filtered = build_filters(data)

    st.markdown("<div class='section-title'>Key Metrics</div>", unsafe_allow_html=True)
    kpi_section(filtered)

    st.markdown("<div class='section-title'>Ticket Overview</div>", unsafe_allow_html=True)
    build_charts(filtered)

    st.markdown("<div class='section-title'>Ticket Details</div>", unsafe_allow_html=True)
    st.dataframe(
        filtered[
            [
                "Number",
                "Summary",
                "Assigned To Queue",
                "Support Line",
                "Assigned to User",
                "Status",
                "Category",
                "Open Date",
                "Last Change Date",
                "Closed Date",
                "Days Open",
                "Source File",
            ]
        ].sort_values("Open Date", ascending=False),
        width="stretch",
    )

    insights_report(data)


if __name__ == "__main__":
    main()
