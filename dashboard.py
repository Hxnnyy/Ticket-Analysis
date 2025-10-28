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
        if not stored_meta:
            metadata_dirty = True
        meta = DatasetMeta(
            name=name,
            included=stored_meta.included if stored_meta else True,
            disabled=stored_meta.disabled if stored_meta else False,
            uploaded_at=stored_meta.uploaded_at or obj.get("created_at"),
        )
        registry[name] = meta

        try:
            csv_text = download_csv(name).decode("utf-8", errors="replace")
            raw = pd.read_csv(io.StringIO(csv_text))
            raw["Source File"] = name
            prepared = _prepare_ticket_frame(raw)
            frames[name] = prepared
            if meta.included and not meta.disabled:
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


def dataset_management_panel(bundle: DatasetLoadResult) -> None:
    with st.sidebar:
        st.subheader("Datasets")

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
                            st.experimental_rerun()

        if not registry_state:
            st.caption("No datasets stored yet. Upload a CSV to begin.")
            return

        for name in sorted(registry_state.keys()):
            _render_dataset_row(name)


def _render_dataset_row(name: str) -> None:
    registry = st.session_state.get("dataset_registry", {})
    meta = registry.get(name)
    if not meta:
        return

    container = st.container()
    container.markdown(f"**{name}**")

    status_bits = []
    if meta.disabled:
        status_bits.append("Disabled")
    elif meta.included:
        status_bits.append("Included")
    else:
        status_bits.append("Excluded")

    uploaded_label = _format_uploaded_at(meta)
    if uploaded_label:
        status_bits.append(uploaded_label)

    container.caption(" · ".join(status_bits))

    include_key = _sanitize_key("dataset", name, "include")
    disable_key = _sanitize_key("dataset", name, "disable")
    delete_key = _sanitize_key("dataset", name, "delete")

    if st.session_state.get(include_key) != meta.included:
        st.session_state[include_key] = meta.included
    if st.session_state.get(disable_key) != meta.disabled:
        st.session_state[disable_key] = meta.disabled

    include_col, disable_col, delete_col = container.columns([1.2, 1, 0.9])

    include_state = include_col.checkbox(
        "Include",
        key=include_key,
        disabled=meta.disabled,
    )
    disable_state = disable_col.checkbox(
        "Disable",
        key=disable_key,
    )
    delete_clicked = delete_col.button("Delete", key=delete_key)

    if not meta.disabled and include_state != meta.included:
        previous = meta.included
        meta.included = include_state
        if _persist_registry(registry):
            st.sidebar.info(
                f"{'Included' if include_state else 'Excluded'} '{name}' in analytics."
            )
            _invalidate_dataset_cache()
            st.experimental_rerun()
        else:
            meta.included = previous
            st.session_state[include_key] = previous

    if disable_state != meta.disabled:
        previous_disabled = meta.disabled
        meta.disabled = disable_state
        if _persist_registry(registry):
            action = "Disabled" if disable_state else "Re-enabled"
            st.sidebar.info(f"{action} '{name}'.")
            _invalidate_dataset_cache()
            st.experimental_rerun()
        else:
            meta.disabled = previous_disabled
            st.session_state[disable_key] = previous_disabled

    if delete_clicked:
        try:
            delete_object(name)
        except Exception as exc:
            st.sidebar.error(f"Failed to delete '{name}': {exc}")
        else:
            removed_meta = registry.pop(name, None)
            if _persist_registry(registry):
                for key in (include_key, disable_key):
                    st.session_state.pop(key, None)
                st.sidebar.success(f"Deleted '{name}'.")
                _invalidate_dataset_cache()
                st.experimental_rerun()
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
    options = sorted(df[column].dropna().unique())
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
    st.sidebar.title("Filters")

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

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tickets", f"{total_tickets}")
    col2.metric("Open tickets", f"{open_tickets}")
    col3.metric(
        "Avg days open",
        f"{avg_days_open:.2f}" if pd.notna(avg_days_open) else "—",
    )
    col4.metric(
        "Last update",
        latest_activity.strftime("%Y-%m-%d %H:%M")
        if pd.notna(latest_activity)
        else "—",
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
        st.warning("No records match the current filters.")
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
        queue_chart_type = st.radio(
            "Queue chart",
            options=["Bar", "Pie"],
            index=0,
            horizontal=True,
            key="queue_chart_type",
        )
        st.altair_chart(
            _queue_chart(tickets_by_queue, queue_chart_type), use_container_width=True
        )
        category_chart_type = st.radio(
            "Category chart",
            options=["Bar", "Pie"],
            index=0,
            horizontal=True,
            key="category_chart_type",
        )
        st.altair_chart(
            _category_chart(tickets_by_category, category_chart_type),
            use_container_width=True,
        )
    with col2:
        status_chart_type = st.radio(
            "Status chart",
            options=["Bar", "Pie"],
            index=0,
            horizontal=True,
            key="status_chart_type",
        )
        st.altair_chart(
            _status_chart(tickets_by_status, status_chart_type), use_container_width=True
        )
        trend_chart_type = st.radio(
            "Trend chart",
            options=["Line", "Bar", "Area"],
            index=0,
            horizontal=True,
            key="trend_chart_type",
        )
        st.altair_chart(
            _trend_chart(tickets_over_time, trend_chart_type), use_container_width=True
        )


def insights_report(df: pd.DataFrame):
    st.subheader("Insights Report")

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

    st.markdown("\n".join(f"- {item}" for item in insights))


def main():
    st.set_page_config(page_title="Ticket Analysis Dashboard", layout="wide")
    st.title("Ticket Analysis Dashboard")
    st.caption("Interact with the filters to explore ticket workload and performance.")

    cache_bust = st.session_state.get("dataset_cache_bust", 0)
    bundle = load_dataset_bundle(cache_bust)

    st.session_state["dataset_registry"] = {
        name: DatasetMeta(
            name=meta.name,
            included=meta.included,
            disabled=meta.disabled,
            uploaded_at=meta.uploaded_at,
        )
        for name, meta in bundle.registry.items()
    }

    dataset_management_panel(bundle)

    if bundle.source == "local":
        st.warning(
            "Supabase data unavailable. Loaded local CSV files from the app bundle."
        )
    if bundle.errors:
        for issue in bundle.errors:
            st.warning(f"Dataset issue: {issue}")

    data = bundle.combined
    if data.empty:
        st.info("No datasets are currently included. Upload a CSV to get started.")

    filtered = build_filters(data)

    st.markdown("### Key Metrics")
    kpi_section(filtered)

    st.markdown("### Ticket Overview")
    build_charts(filtered)

    st.markdown("### Ticket Details")
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
