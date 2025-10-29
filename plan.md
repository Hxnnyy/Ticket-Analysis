# plan.md

## Context
- Repo: Ticket Analysis
- Goal (week): Stabilise and polish the ticket dashboard UI across desktop and mobile.
- Constraints: Follow AGENTS.md directives, keep diffs focused, validate changes with Playwright on desktop + iPhone 15.

## Next Actions (atomic, <=7)
1. [x] Re-run Context7 lookups (Altair + Streamlit + streamlit-shadcn) and capture actionable notes for open UI defects (blocked – service unavailable, documented).
2. [x] Realign sidebar dataset card markup/CSS to centre content and remove stray ghost bubble container.
3. [ ] Restyle `Include in dashboard` switch, delete button, and chart view tabs to eliminate grey backdrops and position toggles cleanly.
4. [ ] Strip duplicate title markup and redundant bubble wrappers in chart section to avoid double headers/empty cards.
5. [ ] Update Altair specs to rely on single titles, enforce integer-only tick marks, and share palette/background tokens.
6. [x] Add a visible sidebar reopen affordance when collapsed, following Streamlit sidebar state patterns.
7. [ ] Validate desktop + iPhone 15 views via Playwright and sync plan/test notes.

## Notes / Decisions
- 2025-10-29 13:05 UTC: Context7 endpoints returned channel-closed errors for Altair/Streamlit queries; proceeding with existing guidance and will retry later.
- Sidebar card alignment fix: wrap dataset card + controls inside a `.dataset-cluster` flex stack and convert the card layout to centred column flow to eliminate the stray decorative bubble above the controls.
- Custom floating toggle: injects a branded control that forwards clicks to Streamlit’s native collapse button and repositions itself when the sidebar expands, guaranteeing a visible reopen affordance.

## Artifacts
- artifacts/playwright/dashboard-desktop.png
- artifacts/playwright/dashboard-iphone15.png
- artifacts/playwright/dashboard-desktop-step2.png
- artifacts/playwright/dashboard-iphone15-step2.png
- artifacts/playwright/dashboard-desktop-step6.png
- artifacts/playwright/dashboard-iphone15-step6.png

## Done
- [2025-10-29] Documented Context7 outage and captured baseline layout screenshots for step 2.
- [2025-10-29] Centred dataset cards and introduced the floating sidebar toggle with refreshed Playwright captures.
