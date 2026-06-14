# Streamlit Keep-Awake

Streamlit Community Cloud may put the budget app to sleep after inactivity. This repository includes a GitHub Actions workflow that pings the deployed app every 10 minutes:

- Workflow: `.github/workflows/keep-streamlit-awake.yml`
- Default URL: `https://kamei-lab-budget.streamlit.app/`
- Manual run: GitHub Actions -> Keep Streamlit Awake -> Run workflow

If the deployed Streamlit URL changes, set a repository variable named `STREAMLIT_APP_URL` in GitHub:

1. Open the GitHub repository.
2. Go to Settings -> Secrets and variables -> Actions -> Variables.
3. Add or update `STREAMLIT_APP_URL` with the full Streamlit app URL.

This reduces unwanted sleep, but it cannot prevent restarts caused by Streamlit maintenance, dependency errors, quota limits, or app crashes.

The workflow treats HTTP 2xx and 3xx responses as success. This is intentional: password-protected Streamlit apps often return a login redirect, and that request is still enough to wake the app.
