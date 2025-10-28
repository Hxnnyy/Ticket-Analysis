# Deployment & Configuration

## Environment Variables

Set the following variables locally (e.g. via `.env` or your shell) and on Streamlit Cloud via *App settings → Secrets*:

| Variable | Purpose | Default |
| --- | --- | --- |
| `SUPABASE_URL` | Supabase project URL | `https://lkffiqvyrjtqptvjoksb.supabase.co` |
| `SUPABASE_ANON_KEY` | Supabase anon/publishable key | Provided anon key |
| `SUPABASE_BUCKET` | Storage bucket for CSV files | `ticket-csvs` |
| `SUPABASE_METADATA_OBJECT` | JSON object tracking dataset status | `_dataset_registry.json` |
| `SUPABASE_DISABLE` | Set to `1` to force local/offline mode (used by tests) | not set |

> The anon key is safe to ship with the client, but treat it as a secret in deployment platforms so it can be rotated without code changes.

## Supabase Setup

1. Create (or reuse) the project with ID `lkffiqvyrjtqptvjoksb`.
2. In Supabase Storage, add a bucket named `ticket-csvs` with public read access.  
   Grant authenticated users `INSERT`, `UPDATE`, and `DELETE` privileges if row-level security is enabled.
3. No explicit table is required—the app stores dataset metadata in `_dataset_registry.json` within the same bucket.

## Local Development

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   pip install -r requirements.txt
   ```
2. Export the Supabase variables (or place them in `.streamlit/secrets.toml`):
   ```bash
   set SUPABASE_URL=https://lkffiqvyrjtqptvjoksb.supabase.co
   set SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxrZmZpcXZ5cmp0cXB0dmpva3NiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE2MzE4NjUsImV4cCI6MjA3NzIwNzg2NX0.TVq7mhSJSGEuOw8A9x5UEyOGnnm8Y5S9PGnNEDbLhGE
   ```
3. Run the dashboard:
   ```bash
   streamlit run dashboard.py
   ```
4. Use `SUPABASE_DISABLE=1` when you want to work entirely with the bundled sample CSVs.

## Streamlit Cloud Deployment

1. Push the repository to GitHub.
2. In Streamlit Cloud, create a new app that points to `dashboard.py`.
3. Under *Settings → Secrets*, add:
   ```toml
   SUPABASE_URL="https://lkffiqvyrjtqptvjoksb.supabase.co"
   SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxrZmZpcXZ5cmp0cXB0dmpva3NiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE2MzE4NjUsImV4cCI6MjA3NzIwNzg2NX0.TVq7mhSJSGEuOw8A9x5UEyOGnnm8Y5S9PGnNEDbLhGE"
   SUPABASE_BUCKET="ticket-csvs"
   SUPABASE_METADATA_OBJECT="_dataset_registry.json"
   ```
4. Streamlit Cloud automatically installs packages from `requirements.txt`. No additional build steps are required.
5. First-time deployment will create `_dataset_registry.json` on demand; ensure the bucket allows writes from the anon key.
6. Share the app URL with collaborators—anyone with the link can upload, disable, or delete CSV datasets (2 MB limit, unique filenames).

## Testing & CI

- Playwright tests rely on local CSV fixtures. Run them with:
  ```bash
  SUPABASE_DISABLE=1 pytest
  ```
- The same flag is set in the test suite to avoid external calls during automation.
