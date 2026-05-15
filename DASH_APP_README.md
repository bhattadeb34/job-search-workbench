# Dash Job Search Workbench

Run the Dash version:

```bash
cd /Users/dxb5775/Downloads/job-search-workbench
/usr/local/bin/python3 -m pip install -r requirements.txt
/usr/local/bin/python3 dash_job_workbench.py
```

Then open:

```text
http://127.0.0.1:8050
```

The Dash app uses a frontend/backend split:

- Launcher: `dash_job_workbench.py`
- App factory: `workbench/app.py`
- Layout: `workbench/ui/layout.py`
- Components: `workbench/ui/components.py`
- Callbacks: `workbench/callbacks.py`
- Backend service layer: `workbench/backend.py`
- Styling: `assets/dash_job_workbench.css`

The backend service layer wraps the existing scraper scripts:

- `job_scraper.py`
- `company_career_scraper.py`
- `clean_outlook_companies.py`

It also wraps the AI helpers in:

- `sim_eng_ai.py`

The primary app flow is:

1. Load a candidate profile from pasted text, upload, or URL.
2. Enter exact search phrases, job titles, and skills.
3. Optionally use AI to suggest or review keywords.
4. Run the broad job search.
5. Review a searchable/filterable table and source chart.
6. Optionally score jobs with AI.
7. Select a job and ask AI for a fit explanation or cover letter.
8. Optionally run company-page search from a company watchlist.

## AI features

AI features need a Gemini API key. You can either:

- paste it into the sidebar at runtime, or
- export it before launching:

```bash
export GEMINI_API_KEY="your_key_here"
/usr/local/bin/python3 dash_job_workbench.py
```

AI features include:

- profile text extraction from TXT, MD, PDF, and DOCX uploads
- profile extraction from a URL
- keyword suggestions from the candidate profile
- keyword quality review
- job scoring with score/reason columns
- selected-job fit analysis
- selected-job cover letter drafting

Outputs are saved under:

```text
workspace/job_csvs/sim_eng/
workspace/job_chunks/sim_eng/
```
