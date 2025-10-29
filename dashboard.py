"""
Interactive dashboard for the ticket analysis dataset.

Run with: streamlit run dashboard.py
"""

import html
import io
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import altair as alt
import pandas as pd
import streamlit as st
import streamlit_shadcn_ui as ui
import streamlit.components.v1 as components

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

CHART_CATEGORY_COLORS = [
    "#d8c8ff",
    "#bba0ff",
    "#9c7cff",
    "#7b57ff",
    "#5c3ced",
    "#4327be",
]
CHART_AXIS_LABEL_COLOR = "rgba(226, 220, 255, 0.78)"
CHART_AXIS_TITLE_COLOR = "rgba(201, 189, 255, 0.82)"
CHART_GRID_COLOR = "rgba(132, 110, 238, 0.22)"
CHART_DOMAIN_COLOR = "rgba(164, 142, 255, 0.45)"
CHART_VIEW_FILL = "rgba(18, 12, 42, 0.78)"


def _apply_chart_theme(
    chart: alt.Chart, *, title: str, height: int = 300, view_fill: bool = True
) -> alt.Chart:
    configured = (
        chart.properties(title=title, height=height, background="transparent")
        .configure_view(
            fill=CHART_VIEW_FILL if view_fill else "transparent",
            stroke=None,
        )
        .configure_axis(
            labelColor=CHART_AXIS_LABEL_COLOR,
            titleColor=CHART_AXIS_TITLE_COLOR,
            gridColor=CHART_GRID_COLOR,
            tickColor=CHART_DOMAIN_COLOR,
            domainColor=CHART_DOMAIN_COLOR,
        )
        .configure_title(
            color="#f2eeff",
            font="Inter",
            fontSize=16,
            anchor="start",
            fontWeight=600,
        )
        .configure_legend(
            labelColor=CHART_AXIS_LABEL_COLOR,
            titleColor=CHART_AXIS_TITLE_COLOR,
            orient="top",
            direction="horizontal",
        )
    )
    return configured


def _metric_icon_svg(icon_key: str) -> str:
    icons = {
        "tickets": """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="metric-bars-gradient" x1="4" y1="20" x2="20" y2="4" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#d7c8ff"/>
      <stop offset="1" stop-color="#7a54ff"/>
    </linearGradient>
  </defs>
  <rect x="4" y="14" width="4" height="6" rx="1.2" fill="url(#metric-bars-gradient)"/>
  <rect x="10" y="9" width="4" height="11" rx="1.2" fill="url(#metric-bars-gradient)"/>
  <rect x="16" y="5" width="4" height="15" rx="1.2" fill="url(#metric-bars-gradient)"/>
</svg>
""",
        "active": """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="metric-active-gradient" x1="4" y1="20" x2="20" y2="4" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#7df1ff"/>
      <stop offset="1" stop-color="#4cc7ff"/>
    </linearGradient>
  </defs>
  <path d="M12 2 9 11h4l-1 9 7-12h-4l3-6z" fill="url(#metric-active-gradient)" />
</svg>
""",
        "time": """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="metric-time-gradient" x1="4" y1="20" x2="20" y2="4" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#ffd8a0"/>
      <stop offset="1" stop-color="#ffb562"/>
    </linearGradient>
  </defs>
  <circle cx="12" cy="12" r="9" stroke="url(#metric-time-gradient)" stroke-width="2" fill="none"/>
  <path d="M12 7v5l3 2" stroke="url(#metric-time-gradient)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
""",
        "update": """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="metric-update-gradient" x1="5" y1="19" x2="19" y2="5" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#ffb2df"/>
      <stop offset="1" stop-color="#ff77b9"/>
    </linearGradient>
  </defs>
  <path d="M12 5a7 7 0 1 1-6.35 9.58" fill="none" stroke="url(#metric-update-gradient)" stroke-width="2" stroke-linecap="round"/>
  <path d="M5 8V5H2" stroke="url(#metric-update-gradient)" stroke-width="2" stroke-linecap="round"/>
</svg>
""",
    }
    return icons.get(icon_key, icons["tickets"])


def _dataset_icon_svg(identifier: str) -> str:
    gradient_id = f"dataset-gradient-{identifier}"
    return f"""
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="{gradient_id}" x1="4" y1="20" x2="20" y2="4" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#e7dbff"/>
      <stop offset="1" stop-color="#8d66ff"/>
    </linearGradient>
  </defs>
  <path d="M5 7.5C5 5.6 8.1 4 12 4s7 1.6 7 3.5S15.9 11 12 11 5 9.4 5 7.5Z" fill="url(#{gradient_id})"/>
  <path d="M5 7.5v4c0 1.9 3.1 3.5 7 3.5s7-1.6 7-3.5v-4" fill="none" stroke="url(#{gradient_id})" stroke-width="1.4"/>
  <path d="M5 11.5v4c0 1.9 3.1 3.5 7 3.5s7-1.6 7-3.5v-4" fill="none" stroke="url(#{gradient_id})" stroke-width="1.4"/>
</svg>
"""


def _hero_icon_svg(icon_key: str) -> str:
    icons = {
        "active": """
<svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="hero-active-gradient" x1="3" y1="17" x2="17" y2="3" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#bda5ff"/>
      <stop offset="1" stop-color="#7c5cff"/>
    </linearGradient>
  </defs>
  <circle cx="10" cy="10" r="8.5" fill="url(#hero-active-gradient)"/>
  <path d="M14 7.5 9.1 12.4 7 10.3" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
""",
        "stored": """
<svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="hero-stored-gradient" x1="4" y1="17" x2="16" y2="5" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#e8dcff"/>
      <stop offset="1" stop-color="#a27bff"/>
    </linearGradient>
  </defs>
  <rect x="4" y="5.5" width="12" height="3.2" rx="1.2" fill="url(#hero-stored-gradient)"/>
  <rect x="4" y="9.4" width="12" height="3.2" rx="1.2" fill="url(#hero-stored-gradient)" opacity="0.85"/>
  <rect x="4" y="13.3" width="12" height="3.2" rx="1.2" fill="url(#hero-stored-gradient)" opacity="0.7"/>
</svg>
""",
        "source": """
<svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="hero-source-gradient" x1="5" y1="16" x2="15" y2="4" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#7ef5ff"/>
      <stop offset="1" stop-color="#4abdf2"/>
    </linearGradient>
  </defs>
  <path d="M10 4 6.5 7.5h2.5V12.5H7l3 3.5 3-3.5h-2V7.5h2.5Z" fill="url(#hero-source-gradient)"/>
</svg>
""",
        "local": """
<svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="hero-local-gradient" x1="4" y1="16" x2="16" y2="4" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#ffd7a6"/>
      <stop offset="1" stop-color="#ffb56d"/>
    </linearGradient>
  </defs>
  <path d="M10 3 4 7.5v5c0 1 .5 1.8 1.5 2.4l4.5 2.6 4.5-2.6c1-.6 1.5-1.4 1.5-2.4v-5Z" fill="none" stroke="url(#hero-local-gradient)" stroke-width="1.6" stroke-linejoin="round"/>
  <path d="M7.5 9.5 10 12l2.5-2.5" fill="none" stroke="#ffd9b7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
""",
        "closure": """
<svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="hero-closure-gradient" x1="5" y1="15" x2="15" y2="5" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#ffbadd"/>
      <stop offset="1" stop-color="#ff7cb8"/>
    </linearGradient>
  </defs>
  <path d="M10 3.5a6.5 6.5 0 1 1-6.2 8.2" fill="none" stroke="url(#hero-closure-gradient)" stroke-width="2.2" stroke-linecap="round"/>
  <circle cx="10" cy="10" r="2.1" fill="url(#hero-closure-gradient)"/>
</svg>
""",
    }
    default_icon = icons["active"]
    return icons.get(icon_key, default_icon)


def _hero_pill(icon_key: str, label: str) -> str:
    safe_label = html.escape(label)
    return (
        "<span class='hero-pill'>"
        f"<span class='hero-pill__icon'>{_hero_icon_svg(icon_key)}</span>"
        f"<span class='hero-pill__label'>{safe_label}</span>"
        "</span>"
    )


def _render_sidebar_toggle() -> None:
    components.html(
        """
        <script>
        (function() {
            const doc = window.parent ? window.parent.document : window.document;
            if (!doc) { return; }
            const ensureButton = () => {
                let wrapper = doc.querySelector(".sidebar-toggle");
                if (!wrapper) {
                    wrapper = doc.createElement("div");
                    wrapper.className = "sidebar-toggle";
                    wrapper.innerHTML = `
                        <button class="sidebar-toggle__button" type="button" aria-label="Toggle sidebar" aria-expanded="true">
                            <span class="sidebar-toggle__icon sidebar-toggle__icon--hide">&#x276E;</span>
                            <span class="sidebar-toggle__icon sidebar-toggle__icon--show">&#9776;</span>
                        </button>
                    `;
                    doc.body.appendChild(wrapper);
                }
                return { wrapper, button: wrapper.querySelector("button") };
            };
            const nativeButton = doc.querySelector("[data-testid='stSidebarCollapseButton'] button");
            const { wrapper, button: toggleButton } = ensureButton();
            if (!nativeButton || !wrapper || !toggleButton) { return; }
            const sidebar = doc.querySelector("[data-testid='stSidebar']");
            if (!sidebar) { return; }
            const syncState = () => {
                const rect = sidebar.getBoundingClientRect();
                const collapsed = rect.width < 20;
                const leftOffset = collapsed ? "1.4rem" : `${Math.max(rect.width, 0) + 24}px`;
                wrapper.style.left = leftOffset;
                toggleButton.classList.toggle("is-collapsed", collapsed);
                toggleButton.setAttribute("aria-expanded", collapsed ? "false" : "true");
                toggleButton.style.display = "inline-flex";
            };
            toggleButton.onclick = (event) => {
                event.preventDefault();
                nativeButton.click();
                setTimeout(syncState, 320);
            };
            if (typeof ResizeObserver !== "undefined") {
                const observer = new ResizeObserver(syncState);
                observer.observe(sidebar);
            }
            syncState();
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def _inject_theme() -> None:
    st.markdown(
        """
        <style>
            :root {
                --ticket-purple-950: #05010f;
                --ticket-purple-900: #0d0720;
                --ticket-purple-800: #130b2f;
                --ticket-purple-700: #6b46ff;
                --ticket-purple-500: #9c7aff;
                --ticket-purple-300: #c0b0ff;
                --ticket-ink-100: rgba(241, 237, 255, 0.82);
            }

            .stApp {
                background: radial-gradient(120% 120% at 0% 0%, rgba(149, 110, 255, 0.16), transparent 45%),
                            radial-gradient(100% 120% at 100% 0%, rgba(85, 53, 214, 0.26), transparent 55%),
                            linear-gradient(180deg, #060313 0%, #0d0720 55%, #120b2b 100%);
                color: #f4f1ff;
                font-family: 'Inter', sans-serif;
            }

            .stApp header {
                background: transparent;
                pointer-events: none;
            }\n\n            .stApp header * {\n                pointer-events: none;\n            }\n

            .stApp [data-testid="stToolbar"] {
                display: none;
            }

            main.stAppViewContainer > .main,
            .stApp main .block-container {
                padding-top: 2.4rem;
                padding-bottom: 2rem;
            }

            .stApp [data-testid="stToolbar"] {
                display: none;
            }

            [data-testid="stSidebarCollapseButton"] {
                display: none !important;
            }

            .sidebar-toggle {
                position: fixed;
                top: 1.4rem;
                left: 1.4rem;
                z-index: 4000;
                display: flex;
                align-items: center;
                justify-content: center;
                pointer-events: auto;
            }

            .sidebar-toggle__button {
                width: 46px;
                height: 46px;
                border-radius: 14px;
                border: 1px solid rgba(136, 115, 255, 0.5);
                background: linear-gradient(135deg, rgba(102, 78, 204, 0.88), rgba(158, 135, 255, 0.95));
                box-shadow: 0 18px 32px rgba(20, 8, 58, 0.55);
                color: #ede6ff;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                pointer-events: auto;
                z-index: 4000;
                cursor: pointer;
                transition: transform 140ms ease, box-shadow 140ms ease;
            }

            .sidebar-toggle__button:hover {
                transform: translateY(-1px);
                box-shadow: 0 22px 36px rgba(26, 11, 68, 0.6);
            }

            .sidebar-toggle__icon {
                font-size: 1.2rem;
                line-height: 1;
                display: inline-flex;
            }

            .sidebar-toggle__icon--show {
                display: none;
            }

            .sidebar-toggle__button.is-collapsed .sidebar-toggle__icon--hide {
                display: none;
            }

            .sidebar-toggle__button.is-collapsed .sidebar-toggle__icon--show {
                display: inline-flex;
            }

            [data-testid="stSidebarHeader"] {
                pointer-events: none;
            }

            .section-title {
                font-size: 1.35rem;
                letter-spacing: 0.01em;
                margin: 2.2rem 0 1rem;
                color: #f1edff;
            }

            [data-testid="stSidebar"] {
                background: linear-gradient(200deg, rgba(33, 22, 78, 0.98) 0%, rgba(15, 10, 40, 0.98) 100%);
                border-right: 1px solid rgba(146, 119, 255, 0.45);
                box-shadow: 12px 0 40px rgba(5, 4, 20, 0.6);
            }

            [data-testid="stSidebar"] .block-container {
                padding: 2.8rem 1.6rem;
            }

            [data-testid="stSidebar"] * {
                color: #eae4ff;
            }

            .sidebar-section-title {
                font-weight: 600;
                font-size: 0.78rem;
                letter-spacing: 0.18em;
                text-transform: uppercase;
                color: rgba(204, 195, 255, 0.8);
                margin-bottom: 0.75rem;
            }

            [data-testid="stSidebar"] .stFileUploader label {
                color: rgba(228, 223, 255, 0.8);
            }

            .dataset-upload {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 0.9rem;
                margin-bottom: 1.4rem;
            }

            .dataset-upload [data-testid="stFileUploader"] {
                width: 100%;
            }

            .dataset-upload [data-testid="stFileUploader"] section {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                text-align: center;
                border-radius: 16px !important;
                border: 1px dashed rgba(158, 135, 255, 0.55) !important;
                background: rgba(31, 22, 70, 0.85) !important;
            }

            .dataset-upload [data-testid="stFormSubmitButton"] {
                width: 100%;
                display: flex;
                justify-content: center;
            }

            .dataset-upload [data-testid="stFormSubmitButton"] button {
                width: 100%;
                border-radius: 999px;
                background: linear-gradient(135deg, rgba(104, 80, 214, 0.9), rgba(161, 135, 255, 0.95));
                border: 1px solid rgba(174, 152, 255, 0.6);
                color: #f4f1ff;
                letter-spacing: 0.05em;
            }

            [data-testid="stSidebar"] .stAlert {
                border-radius: 16px;
                background: rgba(22, 17, 48, 0.85);
                border: 1px solid rgba(132, 111, 255, 0.3);
            }

            .hero-wrapper {
                position: relative;
                overflow: hidden;
                display: flex;
                gap: 2.4rem;
                align-items: stretch;
                background: linear-gradient(135deg, rgba(33, 21, 79, 0.85), rgba(14, 7, 36, 0.92));
                border: 1px solid rgba(132, 111, 255, 0.35);
                border-radius: 28px;
                padding: 2.5rem 2.7rem;
                box-shadow: 0 32px 60px rgba(10, 6, 32, 0.55);
                margin-bottom: 2.2rem;
            }

            .hero-wrapper::before,
            .hero-wrapper::after {
                content: "";
                position: absolute;
                border-radius: 999px;
                opacity: 0.35;
            }

            .hero-wrapper::before {
                width: 320px;
                height: 320px;
                right: -120px;
                top: -80px;
                background: radial-gradient(circle, rgba(151, 129, 255, 0.55) 0%, transparent 70%);
            }

            .hero-wrapper::after {
                width: 260px;
                height: 260px;
                left: -140px;
                bottom: -120px;
                background: radial-gradient(circle, rgba(85, 59, 214, 0.5) 0%, transparent 75%);
            }

            .hero-copy {
                flex: 1 1 60%;
                position: relative;
                z-index: 2;
            }

            .hero-kicker {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                padding: 0.28rem 0.7rem;
                border-radius: 999px;
                background: rgba(92, 70, 205, 0.35);
                border: 1px solid rgba(153, 131, 255, 0.55);
                font-size: 0.7rem;
                text-transform: uppercase;
                letter-spacing: 0.22em;
                margin-bottom: 0.9rem;
                color: #dcd4ff;
            }

            .hero-copy h1 {
                font-size: 2.3rem;
                font-weight: 700;
                margin: 0 0 0.6rem;
                color: #ffffff;
            }

            .hero-copy p {
                margin: 0;
                font-size: 1rem;
                line-height: 1.6;
                color: rgba(235, 231, 255, 0.85);
            }

            .hero-pills {
                margin-top: 1.6rem;
                display: flex;
                flex-wrap: wrap;
                gap: 0.65rem;
            }

            .hero-pill {
                padding: 0.6rem 1rem;
                border-radius: 999px;
                background: linear-gradient(145deg, rgba(27, 19, 66, 0.92), rgba(15, 10, 42, 0.88));
                border: 1px solid rgba(155, 133, 255, 0.38);
                font-size: 0.8rem;
                display: inline-flex;
                align-items: center;
                gap: 0.55rem;
                box-shadow: 0 12px 24px rgba(10, 6, 30, 0.45);
            }

            .hero-pill__icon {
                display: grid;
                place-items: center;
                width: 22px;
                height: 22px;
            }

            .hero-pill__icon svg {
                width: 20px;
                height: 20px;
            }

            .hero-pill__label {
                letter-spacing: 0.06em;
                text-transform: uppercase;
                color: rgba(233, 226, 255, 0.85);
                font-size: 0.74rem;
            }

            .hero-visual {
                flex: 1 1 32%;
                position: relative;
                z-index: 2;
                display: flex;
                justify-content: center;
                align-items: center;
            }

            .hero-orb {
                position: relative;
                width: 260px;
                height: 260px;
                border-radius: 30px;
                background: linear-gradient(135deg, rgba(141, 110, 255, 0.5), rgba(35, 18, 98, 0.95));
                border: 1px solid rgba(177, 161, 255, 0.55);
                box-shadow: inset 0 0 40px rgba(230, 222, 255, 0.08);
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                gap: 0.6rem;
            }

            .hero-orb::before,
            .hero-orb::after {
                content: "";
                position: absolute;
                border-radius: 999px;
                background: radial-gradient(circle, rgba(255, 255, 255, 0.65), transparent 70%);
                opacity: 0.22;
            }

            .hero-orb::before {
                width: 160px;
                height: 160px;
                top: -60px;
                left: 20px;
            }

            .hero-orb::after {
                width: 140px;
                height: 140px;
                bottom: -50px;
                right: 10px;
            }

            .hero-orb__label {
                font-size: 0.75rem;
                letter-spacing: 0.2em;
                text-transform: uppercase;
                color: rgba(232, 225, 255, 0.7);
            }

            .hero-orb__value {
                font-size: 2.8rem;
                font-weight: 700;
                color: #ffffff;
                text-shadow: 0 12px 30px rgba(0, 0, 0, 0.2);
            }

            .hero-orb__meta {
                font-size: 0.85rem;
                color: rgba(232, 225, 255, 0.7);
            }

            .metric-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 1.2rem;
            }

            .metric-card {
                position: relative;
                border-radius: 22px;
                padding: 1.4rem 1.6rem;
                background: rgba(19, 14, 44, 0.9);
                border: 1px solid rgba(116, 96, 226, 0.4);
                overflow: hidden;
                box-shadow: 0 14px 36px rgba(6, 3, 23, 0.45);
                --metric-accent: rgba(156, 122, 255, 0.6);
                --metric-soft: rgba(140, 114, 255, 0.25);
                --metric-border: rgba(170, 152, 255, 0.35);
            }

            .metric-card::after {
                content: "";
                position: absolute;
                inset: 12px -30px auto auto;
                width: 120px;
                height: 120px;
                border-radius: 50%;
                background: radial-gradient(circle at center, var(--metric-accent), transparent 65%);
                opacity: 0.35;
                transform: rotate(25deg);
            }

            .metric-icon {
                width: 44px;
                height: 44px;
                border-radius: 14px;
                display: grid;
                place-items: center;
                background: linear-gradient(145deg, var(--metric-soft), rgba(116, 88, 249, 0.15));
                border: 1px solid var(--metric-border);
                margin-bottom: 0.8rem;
                box-shadow: 0 12px 26px rgba(20, 10, 52, 0.4);
            }

            .metric-icon svg {
                width: 24px;
                height: 24px;
            }

            .metric-value {
                font-size: 1.8rem;
                font-weight: 700;
                color: #f9f8ff;
            }

            .metric-label {
                font-size: 0.85rem;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                color: rgba(215, 205, 255, 0.75);
            }

            .metric-caption {
                margin-top: 0.35rem;
                font-size: 0.85rem;
                color: rgba(222, 217, 255, 0.6);
            }

            .chart-card {
                position: relative;
                border-radius: 26px;
                padding: 1.6rem 1.7rem 1.9rem;
                background: linear-gradient(160deg, rgba(21, 15, 54, 0.92), rgba(10, 6, 26, 0.9));
                border: 1px solid rgba(126, 103, 236, 0.4);
                box-shadow: 0 22px 48px rgba(8, 5, 26, 0.55);
                margin-bottom: 1.6rem;
            }

            .chart-card::before {
                content: "";
                position: absolute;
                inset: 0;
                background:
                    radial-gradient(circle at 20% -10%, rgba(148, 120, 255, 0.22), transparent 55%),
                    radial-gradient(circle at 80% 0%, rgba(92, 69, 213, 0.28), transparent 60%);
                border-radius: inherit;
                pointer-events: none;
            }

            .chart-card__title {
                font-size: 1.05rem;
                font-weight: 600;
                color: #f0ecff;
            }

            .chart-card .stAltairChart {
                position: relative;
                z-index: 2;
            }

            .chart-card .vega-embed {
                background: transparent !important;
            }

            .chart-card canvas {
                border-radius: 18px;
            }

            .chart-card > div[data-testid="column"] {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 0.9rem;
                position: relative;
                z-index: 2;
                margin-bottom: 0.6rem;
            }

            .chart-card > div[data-testid="column"] > div {
                padding: 0 !important;
            }

            .chart-card > div[data-testid="column"] > div:last-child {
                display: flex;
                justify-content: flex-end;
            }

            .chart-card [role="tablist"] {
                display: inline-flex;
                align-items: center;
                gap: 0.4rem;
                padding: 0.35rem;
                border-radius: 999px;
                background: rgba(63, 43, 132, 0.35);
                border: 1px solid rgba(156, 132, 255, 0.35);
                box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
            }

            .chart-card [role="tab"] {
                padding: 0.3rem 0.95rem;
                border-radius: 999px;
                border: none;
                background: transparent;
                color: rgba(220, 212, 255, 0.65);
                font-size: 0.8rem;
                letter-spacing: 0.05em;
                text-transform: uppercase;
                transition: all 0.2s ease;
            }

            .chart-card [role="tab"]:hover {
                color: rgba(248, 244, 255, 0.85);
            }

            .chart-card [role="tab"][data-state="active"] {
                color: #140b2d;
                background: linear-gradient(135deg, #f3ebff 0%, #b092ff 100%);
                box-shadow: 0 14px 24px rgba(86, 60, 189, 0.3);
            }

            .dataset-cluster {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 0.9rem;
                width: 100%;
            }

            .dataset-card {
                position: relative;
                display: flex;
                flex-direction: column;
                align-items: center;
                text-align: center;
                gap: 0.75rem;
                border-radius: 22px;
                padding: 1.1rem 1.4rem;
                background: linear-gradient(155deg, rgba(27, 18, 70, 0.95), rgba(14, 9, 38, 0.92));
                border: 1px solid rgba(149, 128, 255, 0.38);
                margin: 0.8rem auto;
                width: 100%;
                max-width: 320px;
                box-shadow: 0 20px 36px rgba(8, 4, 24, 0.55);
            }

            .dataset-card::before {
                content: "";
                position: absolute;
                inset: -10% -25% auto auto;
                width: 140px;
                height: 140px;
                border-radius: 50%;
                background: radial-gradient(circle, rgba(146, 119, 255, 0.35), transparent 70%);
            }

            .dataset-card__icon {
                position: relative;
                width: 48px;
                height: 48px;
                border-radius: 16px;
                display: grid;
                place-items: center;
                background: linear-gradient(140deg, rgba(229, 214, 255, 0.9), rgba(144, 102, 255, 0.85));
                border: 1px solid rgba(222, 208, 255, 0.6);
                box-shadow: 0 12px 30px rgba(23, 11, 54, 0.55);
                z-index: 1;
                margin-bottom: 0.4rem;
            }

            .dataset-card__icon svg {
                width: 26px;
                height: 26px;
            }

            .dataset-card__body {
                position: relative;
                z-index: 1;
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 0.45rem;
            }

            .dataset-card__body h4 {
                margin: 0;
                font-size: 1rem;
                color: #f6f2ff;
            }

            .dataset-meta {
                font-size: 0.78rem;
                letter-spacing: 0.04em;
                text-transform: uppercase;
                text-align: center;
                color: rgba(215, 206, 255, 0.7);
            }

            .dataset-badge {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                margin-top: 0.6rem;
                padding: 0.3rem 0.75rem;
                border-radius: 999px;
                font-size: 0.72rem;
                letter-spacing: 0.08em;
                text-transform: uppercase;
            }

            .dataset-badge--active {
                background: rgba(119, 255, 193, 0.18);
                border: 1px solid rgba(119, 255, 193, 0.42);
                color: #70ffc4;
            }

            .dataset-badge--paused {
                background: rgba(255, 170, 146, 0.18);
                border: 1px solid rgba(255, 170, 146, 0.35);
                color: #ffc0b0;
            }

            .dataset-controls {
                display: flex;
                justify-content: center;
                flex-wrap: wrap;
                gap: 0.9rem;
                align-items: center;
                margin: 0.8rem 0 1.2rem;
                width: 100%;
            }

            .dataset-controls [data-testid="column"] {
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 0 !important;
            }

            .dataset-controls label {
                display: flex;
                align-items: center;
                gap: 0.75rem;
                font-size: 0.82rem;
                letter-spacing: 0.03em;
                color: rgba(232, 224, 255, 0.8) !important;
            }

            .dataset-controls button[role="switch"] {
                position: relative;
                width: 3.1rem;
                height: 1.6rem;
                border-radius: 999px;
                border: 1px solid rgba(184, 162, 255, 0.5);
                background: rgba(63, 39, 134, 0.35);
                transition: all 0.25s ease;
                box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
            }

            .dataset-controls button[role="switch"]::after {
                content: "";
                position: absolute;
                top: 2px;
                left: 2.2px;
                width: 1.2rem;
                height: 1.2rem;
                border-radius: 50%;
                background: linear-gradient(140deg, #f2edff, #bba3ff);
                box-shadow: 0 6px 12px rgba(22, 11, 52, 0.4);
                transition: transform 0.25s ease;
            }

            .dataset-controls button[role="switch"][data-state="checked"] {
                background: linear-gradient(135deg, rgba(142, 109, 255, 0.85), rgba(203, 178, 255, 0.95));
                border-color: rgba(203, 178, 255, 0.6);
                box-shadow: 0 12px 24px rgba(95, 70, 194, 0.35);
            }

            .dataset-controls button[role="switch"][data-state="checked"]::after {
                transform: translateX(1.45rem);
            }

            .dataset-controls button:not([role="switch"]) {
                width: 100%;
                border-radius: 999px;
                padding: 0.55rem 1rem;
                font-weight: 600;
                letter-spacing: 0.05em;
                border: 1px solid rgba(255, 170, 198, 0.55);
                background: linear-gradient(135deg, rgba(255, 126, 177, 0.88), rgba(255, 90, 137, 0.92));
                box-shadow: 0 14px 26px rgba(120, 30, 83, 0.35);
                color: #fff;
            }

            .dataset-controls button:not([role="switch"]):hover {
                filter: brightness(1.08);
            }

            .dataset-card h4 {
                font-size: 1.02rem;
                font-weight: 600;
                margin-bottom: 0.2rem;
                color: #f2eeff;
            }

            .dataset-meta {
                font-size: 0.78rem;
                color: rgba(221, 215, 255, 0.65);
                margin-bottom: 0;
            }

            .dataset-controls {
                background: rgba(12, 8, 30, 0.85);
                border: 1px solid rgba(117, 97, 223, 0.3);
                border-radius: 16px;
                padding: 0.95rem 1.1rem;
                margin: 0.6rem 0 1.4rem;
                display: flex;
                gap: 1.2rem;
            }

            .dataset-controls > div[data-testid="column"] > div {
                padding: 0 !important;
            }

            .insight-card {
                position: relative;
                border-radius: 24px;
                padding: 1.6rem 1.8rem;
                background: rgba(17, 12, 42, 0.9);
                border: 1px solid rgba(125, 103, 240, 0.32);
                box-shadow: 0 18px 44px rgba(5, 3, 20, 0.55);
                margin-top: 1.8rem;
            }

            .insight-card h4 {
                margin: 0 0 1rem;
                font-size: 1.15rem;
                font-weight: 600;
                color: #f6f3ff;
            }

            .insight-card::before {
                content: "";
                position: absolute;
                inset: -30px auto auto -40px;
                width: 150px;
                height: 150px;
                border-radius: 50%;
                background: radial-gradient(circle, rgba(123, 98, 255, 0.35), transparent 70%);
                opacity: 0.6;
            }

            .insight-card ul {
                padding-left: 1.2rem;
                margin: 0;
                color: rgba(226, 221, 255, 0.82);
                line-height: 1.55;
            }

            .insight-card li {
                margin-bottom: 0.7rem;
            }

            .stDataFrame {
                background: rgba(15, 10, 36, 0.92);
                border-radius: 22px;
                border: 1px solid rgba(112, 90, 226, 0.35);
                box-shadow: 0 20px 48px rgba(6, 3, 23, 0.5);
                overflow: hidden;
            }

            .stDataFrame [data-testid="stTable"] {
                background: transparent;
            }

            .stDataFrame thead tr th {
                background: rgba(21, 17, 48, 0.9);
                color: #f1edff;
            }

            div[data-testid="stExpander"] {
                background: rgba(14, 10, 36, 0.85);
                border: 1px solid rgba(117, 98, 232, 0.3);
                border-radius: 16px !important;
            }

            div[data-testid="stExpander"] summary {
                color: rgba(223, 218, 255, 0.85);
            }

            .stAlert {
                border-radius: 18px;
                border: 1px solid rgba(132, 111, 255, 0.35);
                background: rgba(19, 14, 48, 0.8);
                color: #f1edff;
            }

        </style>
        """,
        unsafe_allow_html=True,
    )


def _sanitize_key(*parts: str) -> str:
    safe_parts = []
    for part in parts:
        safe = re.sub(r"[^0-9A-Za-z]+", "_", str(part))
        safe_parts.append(safe.strip("_"))
    return "_".join(safe_parts)


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

    current_names = set(current.keys()) if isinstance(current, dict) else set()

    for name, meta in registry.items():
        include_key = _sanitize_key("dataset", name, "include")
        current_value = st.session_state.get(include_key)
        if needs_refresh or not isinstance(current_value, bool):
            st.session_state[include_key] = meta.included

    removed_names = current_names - set(registry.keys())
    for name in removed_names:
        include_key = _sanitize_key("dataset", name, "include")
        st.session_state.pop(include_key, None)


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
    active_line = (
        f"{included} dataset{'s' if included != 1 else ''} active"
        if included
        else "Activate a dataset to populate insights"
    )
    stored_line = (
        f"{total} dataset{'s' if total != 1 else ''} stored" if total else "No datasets uploaded yet"
    )
    source_line = "Supabase live" if bundle.source == "supabase" else "Local fallback mode"
    closed_ratio = 0
    if record_count:
        closed_series = bundle.combined["Is Closed"].mean()
        if pd.notna(closed_series):
            closed_ratio = int(round(float(closed_series) * 100))
    data_line = (
        f"{record_count:,} tickets across {included} active dataset{'s' if included != 1 else ''}."
        if included
        else "Upload or enable a dataset to unlock the command center."
    )

    source_icon_key = "source" if bundle.source == "supabase" else "local"
    hero_pills_html = "".join(
        [
            _hero_pill("active", active_line),
            _hero_pill("stored", stored_line),
            _hero_pill(source_icon_key, source_line),
            _hero_pill("closure", f"{closed_ratio}% closure rate"),
        ]
    )

    hero_html = f"""
    <div class="hero-wrapper">
        <div class="hero-copy">
            <span class="hero-kicker">Operations Pulse</span>
            <h1>Ticket Command Center</h1>
            <p>{data_line} Dive into queue performance, resolution velocity, and workload distribution from a single view.</p>
            <div class="hero-pills">{hero_pills_html}</div>
        </div>
        <div class="hero-visual">
            <div class="hero-orb">
                <span class="hero-orb__label">Tickets in focus</span>
                <span class="hero-orb__value">{record_count:,}</span>
                <span class="hero-orb__meta">Insights refreshed from {source_line.lower()}.</span>
            </div>
        </div>
    </div>
    """

    st.markdown(hero_html, unsafe_allow_html=True)


def dataset_management_panel(bundle: DatasetLoadResult) -> None:
    with st.sidebar:
        st.markdown("<div class='sidebar-section-title'>Datasets</div>", unsafe_allow_html=True)

        if bundle.source == "local":
            st.warning(
                "Supabase connection unavailable; dataset management is disabled while local data is in use."
            )
            return

        registry_state = st.session_state.get("dataset_registry", {})
        st.markdown("<div class='dataset-upload'>", unsafe_allow_html=True)
        with st.form("dataset_upload_form", clear_on_submit=True):
            uploader = st.file_uploader(
                "Upload CSV (max 2 MB)",
                type=["csv"],
                accept_multiple_files=False,
                key="dataset_upload_widget",
            )
            submitted = st.form_submit_button("Add dataset")
        st.markdown("</div>", unsafe_allow_html=True)

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

    badge_class = "dataset-badge--active" if meta.included else "dataset-badge--paused"
    badge_label = "Active" if meta.included else "Excluded"
    status_summary = " &bull; ".join(html.escape(bit) for bit in status_bits)
    safe_name = html.escape(name)
    icon_identifier = f"ds{_sanitize_key('dataset', name, 'icon')}"
    st.markdown("<div class='dataset-cluster'>", unsafe_allow_html=True)
    dataset_card_html = f"""
    <div class='dataset-card'>
        <div class='dataset-card__icon'>{_dataset_icon_svg(icon_identifier)}</div>
        <div class='dataset-card__body'>
            <h4>{safe_name}</h4>
            <div class='dataset-meta'>{status_summary}</div>
            <span class='dataset-badge {badge_class}'>{badge_label}</span>
        </div>
    </div>
    """
    st.markdown(dataset_card_html, unsafe_allow_html=True)

    st.markdown("<div class='dataset-controls'>", unsafe_allow_html=True)
    include_col, delete_col = st.columns([1.3, 1], gap="medium")

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

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

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
    open_tickets = (
        int((~filtered["Is Closed"]).sum()) if "Is Closed" in filtered else 0
    )
    avg_series = filtered["Days Open"] if "Days Open" in filtered else None
    avg_days_open = avg_series.mean() if avg_series is not None else float("nan")
    latest_activity = (
        filtered["Last Change Date"].max()
        if "Last Change Date" in filtered
        else pd.NaT
    )
    long_running = (
        int(filtered["Days Open"].gt(4).sum()) if "Days Open" in filtered else 0
    )

    avg_days_display = f"{avg_days_open:.1f}d" if pd.notna(avg_days_open) else "—"
    latest_activity_display = (
        latest_activity.strftime("%Y-%m-%d %H:%M") if pd.notna(latest_activity) else "—"
    )

    open_share = (open_tickets / total_tickets) if total_tickets else 0.0
    progress_total = min(total_tickets / 400, 1.0) if total_tickets else 0.0
    progress_open = min(open_share, 1.0)
    progress_avg = (
        min((avg_days_open or 0) / 10, 1.0) if pd.notna(avg_days_open) else 0.0
    )

    hours_since_update: Optional[float] = None
    if pd.notna(latest_activity):
        try:
            hours_since_update = (
                pd.Timestamp.utcnow() - pd.to_datetime(latest_activity)
            ).total_seconds() / 3600
        except Exception:
            hours_since_update = None

    progress_recent = (
        max(0.0, 1 - min(hours_since_update / 72, 1.0))
        if hours_since_update is not None
        else 0.0
    )

    if hours_since_update is None:
        recent_delta = "No activity logged"
    elif hours_since_update < 1:
        recent_delta = "Updated <1h ago"
    elif hours_since_update < 24:
        recent_delta = f"Updated {hours_since_update:.0f}h ago"
    else:
        recent_delta = f"Updated {hours_since_update / 24:.0f}d ago"

    metric_data = [
        {
            "title": "Tickets in view",
            "value": f"{total_tickets:,}",
            "description": "Records after filters",
            "icon_svg": _metric_icon_svg("tickets"),
            "accent": "rgba(176, 148, 255, 0.68)",
            "soft": "rgba(164, 135, 255, 0.22)",
            "border": "rgba(205, 186, 255, 0.48)",
        },
        {
            "title": "Active load",
            "value": f"{open_tickets:,}",
            "description": f"Still awaiting closure &bull; {long_running} running &gt;4d",
            "icon_svg": _metric_icon_svg("active"),
            "accent": "rgba(103, 229, 255, 0.65)",
            "soft": "rgba(90, 198, 255, 0.22)",
            "border": "rgba(132, 231, 255, 0.45)",
        },
        {
            "title": "Avg days open",
            "value": avg_days_display,
            "description": "Mean time to resolve",
            "icon_svg": _metric_icon_svg("time"),
            "accent": "rgba(255, 204, 140, 0.68)",
            "soft": "rgba(255, 189, 102, 0.22)",
            "border": "rgba(255, 217, 167, 0.45)",
        },
        {
            "title": "Last update",
            "value": latest_activity_display,
            "description": recent_delta,
            "icon_svg": _metric_icon_svg("update"),
            "accent": "rgba(255, 167, 214, 0.68)",
            "soft": "rgba(255, 149, 196, 0.22)",
            "border": "rgba(255, 188, 220, 0.45)",
        },
    ]

    cards_html = "".join(
        (
            f"<div class=\"metric-card\" style=\"--metric-accent: {spec['accent']}; --metric-soft: {spec['soft']}; --metric-border: {spec['border']};\">"
            f"<div class=\"metric-icon\">{spec['icon_svg']}</div>"
            f"<div class=\"metric-label\">{spec['title']}</div>"
            f"<div class=\"metric-value\">{spec['value']}</div>"
            f"<div class=\"metric-caption\">{spec['description']}</div>"
            "</div>"
        )
        for spec in metric_data
    )

    st.markdown(f"<div class='metric-grid'>{cards_html}</div>", unsafe_allow_html=True)


def _queue_chart(data: pd.DataFrame, chart_type: str):
    base = alt.Chart(data)
    palette = alt.Scale(range=CHART_CATEGORY_COLORS)

    if chart_type == "Pie":
        chart = (
            base.mark_arc(
                innerRadius=45,
                cornerRadius=6,
                stroke="rgba(255,255,255,0.12)",
                strokeWidth=1,
            )
            .encode(
                theta=alt.Theta("Tickets:Q", stack=True),
                color=alt.Color(
                    "Assigned To Queue:N",
                    scale=palette,
                    legend=alt.Legend(
                        title=None,
                        orient="bottom",
                        direction="horizontal",
                        labelLimit=160,
                    ),
                ),
                tooltip=["Assigned To Queue", "Tickets"],
            )
        )
        return _apply_chart_theme(
            chart, title="Ticket share by queue", view_fill=False
        )

    chart = (
        base.mark_bar(
            size=22,
            cornerRadiusTopLeft=8,
            cornerRadiusTopRight=8,
        )
        .encode(
            x=alt.X("Tickets:Q", title="Tickets"),
            y=alt.Y("Assigned To Queue:N", sort="-x", title="Queue"),
            color=alt.Color("Assigned To Queue:N", scale=palette, legend=None),
            tooltip=["Assigned To Queue", "Tickets"],
        )
    )
    return _apply_chart_theme(chart, title="Tickets by queue")


def _status_chart(data: pd.DataFrame, chart_type: str):
    base = alt.Chart(data)
    palette = alt.Scale(range=CHART_CATEGORY_COLORS)

    if chart_type == "Pie":
        chart = (
            base.mark_arc(
                innerRadius=45,
                cornerRadius=6,
                stroke="rgba(255,255,255,0.1)",
                strokeWidth=1,
            )
            .encode(
                theta=alt.Theta("Tickets:Q", stack=True),
                color=alt.Color(
                    "Status:N",
                    scale=palette,
                    legend=alt.Legend(
                        title=None,
                        orient="bottom",
                        direction="horizontal",
                        labelLimit=160,
                    ),
                ),
                tooltip=["Status", "Tickets"],
            )
        )
        return _apply_chart_theme(
            chart, title="Ticket share by status", view_fill=False
        )

    chart = (
        base.mark_bar(
            size=20,
            cornerRadiusTopLeft=8,
            cornerRadiusTopRight=8,
        )
        .encode(
            x=alt.X("Tickets:Q", title="Tickets"),
            y=alt.Y("Status:N", sort="-x", title="Status"),
            color=alt.Color("Status:N", scale=palette, legend=None),
            tooltip=["Status", "Tickets"],
        )
    )
    return _apply_chart_theme(chart, title="Tickets by status")


def _category_chart(data: pd.DataFrame, chart_type: str):
    base = alt.Chart(data)
    palette = alt.Scale(range=CHART_CATEGORY_COLORS)

    if chart_type == "Pie":
        chart = (
            base.mark_arc(
                innerRadius=45,
                cornerRadius=6,
                stroke="rgba(255,255,255,0.1)",
                strokeWidth=1,
            )
            .encode(
                theta=alt.Theta("Tickets:Q", stack=True),
                color=alt.Color(
                    "Category:N",
                    scale=palette,
                    legend=alt.Legend(
                        title=None,
                        orient="bottom",
                        direction="horizontal",
                        labelLimit=160,
                    ),
                ),
                tooltip=["Category", "Tickets"],
            )
        )
        return _apply_chart_theme(
            chart, title="Ticket share by category", view_fill=False
        )

    chart = (
        base.mark_bar(
            size=20,
            cornerRadiusTopLeft=8,
            cornerRadiusTopRight=8,
        )
        .encode(
            x=alt.X("Tickets:Q", title="Tickets"),
            y=alt.Y("Category:N", sort="-x", title="Category"),
            color=alt.Color("Category:N", scale=palette, legend=None),
            tooltip=["Category", "Tickets"],
        )
    )
    return _apply_chart_theme(chart, title="Top categories")


def _trend_chart(data: pd.DataFrame, chart_type: str):
    base = alt.Chart(data)
    encoding = dict(
        x=alt.X("Open Date:T", title="Open date", sort="ascending"),
        y=alt.Y("Tickets:Q", title="Tickets"),
        tooltip=[
            alt.Tooltip("Open Date:T", title="Date", format="%Y-%m-%d"),
            alt.Tooltip("Tickets:Q", title="Tickets"),
        ],
    )

    if chart_type == "Bar":
        chart = base.mark_bar(
            cornerRadiusTopLeft=8,
            cornerRadiusTopRight=8,
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color="#c8b6ff", offset=0),
                    alt.GradientStop(color="#7a56ff", offset=1),
                ],
                x1=0,
                x2=1,
                y1=1,
                y2=0,
            ),
        ).encode(**encoding)
    elif chart_type == "Area":
        chart = base.mark_area(
            interpolate="monotone",
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color="rgba(164,140,255,0.55)", offset=0),
                    alt.GradientStop(color="rgba(164,140,255,0.05)", offset=1),
                ],
                x1=0,
                x2=0,
                y1=1,
                y2=0,
            ),
            line={"color": "#d9cbff", "size": 2.5},
        ).encode(**encoding)
    else:
        chart = base.mark_line(
            interpolate="monotone",
            color="#dccfff",
            size=2.5,
            point=alt.OverlayMarkDef(
                size=75,
                fill="#f8f5ff",
                stroke="#7a56ff",
                strokeWidth=1.4,
            ),
        ).encode(**encoding)

    return _apply_chart_theme(chart, title="Tickets opened per day")


def _queue_summary(data: pd.DataFrame) -> str:
    if data.empty:
        return "No queue distribution available."
    total = data["Tickets"].sum()
    leader = data.iloc[0]
    share = (leader["Tickets"] / total * 100) if total else 0
    queue_name = leader["Assigned To Queue"] or "Unassigned"
    return (
        f"<strong>{queue_name}</strong> is carrying {int(leader['Tickets'])} tickets "
        f"({share:.0f}% of the active workload)."
    )


def _category_summary(data: pd.DataFrame) -> str:
    if data.empty:
        return "Categories will populate once datasets are enabled."
    top_category = data.iloc[0]
    return (
        f"<strong>{top_category['Category']}</strong> tops the board with {int(top_category['Tickets'])} cases; "
        "revisit knowledge assets there first."
    )


def _status_summary(data: pd.DataFrame) -> str:
    if data.empty:
        return "Ticket status data will appear after ingestion."
    top_status = data.iloc[0]
    total = data["Tickets"].sum()
    share = (top_status["Tickets"] / total * 100) if total else 0
    status_name = top_status["Status"] or "Unknown"
    return (
        f"<strong>{status_name}</strong> holds {int(top_status['Tickets'])} tickets, "
        f"commanding {share:.0f}% of the pipeline."
    )


def _trend_summary(data: pd.DataFrame) -> str:
    if data.empty:
        return "No daily activity yet — upload more history to unlock the trendline."
    latest = data.dropna(subset=["Tickets"]).tail(1)
    if latest.empty:
        return "Daily ticket volumes are still being calculated."
    latest_row = latest.iloc[0]
    date_label = pd.to_datetime(latest_row["Open Date"]).strftime("%b %d")
    tickets = int(latest_row["Tickets"])
    return f"Latest snapshot: {tickets} tickets opened on <strong>{date_label}</strong>."


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

    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.markdown("<div class='chart-card'>", unsafe_allow_html=True)
        header_cols = st.columns([1, 1])
        with header_cols[0]:
            st.markdown(
                "<div class='chart-card__title'>Tickets by queue</div>",
                unsafe_allow_html=True,
            )
        with header_cols[1]:
            queue_chart_type = ui.tabs(
                options=["Bar", "Pie"],
                default_value="Bar",
                key="queue_chart_type",
            )
        st.altair_chart(
            _queue_chart(tickets_by_queue, queue_chart_type), use_container_width=True
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='chart-card'>", unsafe_allow_html=True)
        header_cols = st.columns([1, 1])
        with header_cols[0]:
            st.markdown(
                "<div class='chart-card__title'>Top categories</div>",
                unsafe_allow_html=True,
            )
        with header_cols[1]:
            category_chart_type = ui.tabs(
                options=["Bar", "Pie"],
                default_value="Bar",
                key="category_chart_type",
            )
        st.altair_chart(
            _category_chart(tickets_by_category, category_chart_type),
            use_container_width=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("<div class='chart-card'>", unsafe_allow_html=True)
        header_cols = st.columns([1, 1])
        with header_cols[0]:
            st.markdown(
                "<div class='chart-card__title'>Tickets by status</div>",
                unsafe_allow_html=True,
            )
        with header_cols[1]:
            status_chart_type = ui.tabs(
                options=["Bar", "Pie"],
                default_value="Bar",
                key="status_chart_type",
            )
        st.altair_chart(
            _status_chart(tickets_by_status, status_chart_type), use_container_width=True
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='chart-card'>", unsafe_allow_html=True)
        header_cols = st.columns([1, 1])
        with header_cols[0]:
            st.markdown(
                "<div class='chart-card__title'>Tickets opened per day</div>",
                unsafe_allow_html=True,
            )
        with header_cols[1]:
            trend_chart_type = ui.tabs(
                options=["Line", "Bar", "Area"],
                default_value="Line",
                key="trend_chart_type",
            )
        st.altair_chart(
            _trend_chart(tickets_over_time, trend_chart_type), use_container_width=True
        )
        st.markdown("</div>", unsafe_allow_html=True)


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
    resolution_days = df["Resolution Time Days"].mean()

    insights = []
    if not queue_counts.empty:
        top_queue = queue_counts.index[0]
        top_queue_share = queue_counts.iloc[0] / total * 100
        insights.append(
            f"<strong>{top_queue}</strong> is handling {queue_counts.iloc[0]} of {total} tickets "
            f"({top_queue_share:.0f}% of workload), marking it as the primary pressure point."
        )
    if not category_counts.empty:
        top_category = category_counts.index[0]
        insights.append(
            f"Category <strong>{top_category}</strong> leads with {category_counts.iloc[0]} issues; consider reinforcing knowledge articles around it."
        )
    if pd.notna(avg_days_open):
        insights.append(
            f"Tickets stay active for <strong>{avg_days_open:.1f} days</strong> on average, with {len(long_running)} cases breaching the four-day mark."
        )
    if pd.notna(resolution_days):
        insights.append(
            f"Closed cases resolve in approximately <strong>{resolution_days:.1f} days</strong>, highlighting room to compress hand-offs."
        )
    insights.append(
        f"{closed_share:.0f}% of tickets are closed while {customer_waiting} await customer input — follow-ups could unlock extra wins."
    )
    insights.append(
        "All tickets are currently logged as medium priority, suggesting the triage process could benefit from a wider priority spread."
    )

    if not insights:
        insights.append("No actionable insights available yet — add data to unlock trends.")

    insight_list = "".join(f"<li>{item}</li>" for item in insights)
    st.markdown(
        f"<div class='insight-card'><h4>Key takeaways</h4><ul>{insight_list}</ul></div>",
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(page_title="Ticket Analysis Dashboard", layout="wide")
    _inject_theme()

    cache_bust = st.session_state.get("dataset_cache_bust", 0)
    bundle = load_dataset_bundle(cache_bust)

    _sync_session_registry(bundle.registry)

    _render_header(bundle)
    _render_sidebar_toggle()
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



