# Streamlit Keep-Awake

Streamlit Community Cloud may put lab apps to sleep after inactivity. This repository includes a GitHub Actions workflow that pings the deployed apps every 10 minutes:

- Workflow: `.github/workflows/keep-streamlit-awake.yml`
- Default URLs:
  - `https://kamei-lab-budget.streamlit.app/`
  - `https://kamei-lab-tools.streamlit.app/`
  - `https://kamei-lab-roadmap.streamlit.app/`
  - `https://kamei-lab-notebooks-protocols.streamlit.app/`
- Manual run: GitHub Actions -> Keep Streamlit Awake -> Run workflow

If the deployed Streamlit URLs change, set a repository variable named `STREAMLIT_APP_URLS` in GitHub:

1. Open the GitHub repository.
2. Go to Settings -> Secrets and variables -> Actions -> Variables.
3. Add or update `STREAMLIT_APP_URLS` with one full Streamlit app URL per line.

This reduces unwanted sleep, but it cannot prevent restarts caused by Streamlit maintenance, dependency errors, quota limits, or app crashes.

The workflow treats HTTP 2xx and 3xx responses as success. This is intentional: password-protected Streamlit apps often return a login redirect, and that request is still enough to wake the app.
