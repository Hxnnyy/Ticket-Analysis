# Deployment & Configuration

## Environment Variables

Set the following values using `.streamlit/secrets.toml` (recommended) or environment variables:

| Variable | Purpose | Default |
| --- | --- | --- |
| `SUPABASE_URL` | Supabase project URL | *(none – required)* |
| `SUPABASE_ANON_KEY` | Supabase anon/publishable key | *(none – required)* |
| `SUPABASE_BUCKET` | Storage bucket for CSV files | `ticket-csvs` |
| `SUPABASE_METADATA_OBJECT` | JSON object tracking dataset status | `_dataset_registry.json` |
| `SUPABASE_DISABLE` | Set to `1` to force local/offline mode (used by tests) | not set |

> The anon key is safe to expose to the browser, but treat it as a secret in version control so it can be rotated easily.

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
2. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in your project details:
   ```toml
   [supabase]
   url = "https://<project-ref>.supabase.co"
   anon_key = "your-publishable-anon-key"
   bucket = "ticket-csvs"
   metadata_object = "_dataset_registry.json"
   disable = false
   ```
   Alternatively, export the variables via your shell:
   ```bash
   set SUPABASE_URL=https://<project-ref>.supabase.co
   set SUPABASE_ANON_KEY=your-publishable-anon-key
   ```
3. Run the dashboard:
   ```bash
   streamlit run dashboard.py
   ```
4. Use `SUPABASE_DISABLE=1` when you want to work entirely with the bundled sample CSVs.

## Streamlit Cloud Deployment

1. Push the repository to GitHub.
2. In Streamlit Cloud, create a new app that points to `dashboard.py`.
3. Under *Settings → Secrets*, paste the same TOML structure as the local `secrets.toml`:
   ```toml
   [supabase]
   url = "https://<project-ref>.supabase.co"
   anon_key = "your-publishable-anon-key"
   bucket = "ticket-csvs"
   metadata_object = "_dataset_registry.json"
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
