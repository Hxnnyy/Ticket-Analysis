# Feature Plan: Supabase CSV Management

Progress: 100%
- [x] Step 1: Supabase backend plumbing  
  - [x] Add Supabase client helper with project keys and bucket/table constants  
  - [x] Create metadata schema for dataset status persistence  
  - [x] Implement storage fetch/list utilities with error handling
- [x] Step 2: Streamlit data sourcing  
  - [x] Replace local disk loader with Supabase-backed loader and cache invalidation  
  - [x] Ensure schema validation, UTF-8 decoding, and empty-state messaging  
  - [x] Persist include/exclude flags when filters change
- [x] Step 3: Upload & management UI  
  - [x] Build file upload form with size/name validation and Supabase upload  
  - [x] Surface include/exclude toggles and delete controls in the sidebar  
  - [x] Provide user feedback for success, conflicts, and failures
- [x] Step 4: Tests and deployment prep  
  - [x] Update automated tests/mocks for Supabase interactions  
  - [x] Document environment variables and Streamlit Cloud setup steps  
  - [x] List dependencies (requirements) for deployment
