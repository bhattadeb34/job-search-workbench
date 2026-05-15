# Deployment

This repo is deployment-ready for a Plotly Dash web service. The deployed app
uses the Dash interface in `app.py`.

## Production start command

```bash
gunicorn app:server --bind 0.0.0.0:$PORT --workers 2 --timeout 180
```

The same command is in `Procfile` for platforms that detect it automatically.

## Required settings

Set these on the deployment platform:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:server --bind 0.0.0.0:$PORT --workers 2 --timeout 180`
- Python version: `3.10`

## Plotly Cloud

The Plotly Cloud entrypoint is:

```bash
app:app
```

Standard WSGI platforms should use `app:server`.

Publish from the repo root with:

```bash
plotly app publish --project-path . --entrypoint-module app:app --poll-status
```

`python-jobspy` is optional in the scraper code and is intentionally not in the
cloud requirements file so Plotly Cloud can build reliably. If a deployment
platform supports it cleanly, it can be added later for extra external job board
coverage.

## Optional environment variables

- `GEMINI_API_KEY`: enables AI keyword suggestions, AI scoring, fit analysis, and cover letters.
- `PORT`: normally provided by the hosting platform.

## Render quick setup

1. Create a new Web Service.
2. Connect `https://github.com/bhattadeb34/job-search-workbench`.
3. Use branch `main`.
4. Runtime: Python.
5. Build command: `pip install -r requirements.txt`.
6. Start command: `gunicorn app:server --bind 0.0.0.0:$PORT --workers 2 --timeout 180`.
7. Add `GEMINI_API_KEY` under Environment if you want AI features.
8. Deploy.

## How to confirm it is live

- The platform should show the latest deployed commit SHA.
- The public URL should load the Job Search Workbench UI.
- The logs should include a successful Gunicorn boot with no import errors.
- In the app, enter one keyword and confirm the keyword preview updates.
- If `GEMINI_API_KEY` is set, paste a profile and confirm AI buttons respond.
