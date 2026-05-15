# Job Search Workbench

Plotly Dash app for customizable job searching, keyword management, AI keyword suggestions, AI job scoring, fit analysis, and cover-letter drafting.

## Run From GitHub

These are the instructions to send to someone else:

```bash
git clone https://github.com/bhattadeb34/job-search-workbench.git
cd job-search-workbench
python -m pip install -r requirements.txt
python app.py
```

Then open:

```text
http://127.0.0.1:8050
```

If `python` points to the wrong version on their machine, use `python3`:

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

## What They Need

- Python 3.10 or newer.
- Their own AI provider API key if they want AI features.
- Their own keywords, profile text, resume, and job search settings.

The app does not need Streamlit.

## AI Setup

Inside the app, they can:

1. Choose a provider: OpenAI, Gemini, Anthropic, Mistral, or Cohere.
2. Paste their own API key.
3. Click `Test AI`.
4. Choose a model from the dropdown.

For OpenAI, the app can retrieve available text models automatically after the key is verified.

## Main Files

- `app.py`: local and deployment entrypoint.
- `workbench/app.py`: Dash app factory.
- `workbench/ui/layout.py`: page layout.
- `workbench/callbacks.py`: UI behavior.
- `workbench/backend.py`: backend orchestration.
- `sim_eng_ai.py`: AI provider calls.
- `job_scraper.py`: broad job search script.
- `company_career_scraper.py`: company career-page scraper.
- `clean_outlook_companies.py`: company list cleanup.
- `assets/dash_job_workbench.css`: styling.

## Deploy

See `DEPLOYMENT.md` for Plotly Cloud and web-service deployment notes.
