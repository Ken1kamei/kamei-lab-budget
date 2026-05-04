#!/bin/bash
# deploy.sh — Run this AFTER completing the 2 browser steps below.
#
# BROWSER STEP 1 (GCP — ~10 min):
#   a) Go to https://console.cloud.google.com
#   b) Create project "kamei-lab-budget"
#   c) Enable APIs: Google Sheets API + Google Drive API
#   d) IAM & Admin → Service Accounts → Create → name "budget-app" → no role needed
#   e) Click the service account → Keys → Add Key → JSON → Download
#   f) Run: bash scripts/deploy.sh setup-secrets path/to/downloaded-key.json
#
# BROWSER STEP 2 (GitHub — ~2 min):
#   Run: gh auth login   (opens browser once)
#   Then run: bash scripts/deploy.sh push
#
# BROWSER STEP 3 (Streamlit Community Cloud — ~5 min, no CLI exists):
#   See bottom of this file for exact instructions.

set -e
PROJ_DIR="/Users/kkamei/Library/CloudStorage/Dropbox/Shared Folder NYUAD/Budget"
STREAMLIT_DIR="$PROJ_DIR/streamlit_app"
SPREADSHEET_ID="1Ga6kOPohYxqQbt9ZoNXUma9Tf3cNmlxCJdvxp5edVWE"
PI_EMAIL="ken1kamei@nyu.edu"
GITHUB_REPO="kamei-lab-budget"

cmd="${1:-help}"

case "$cmd" in

  setup-secrets)
    KEY_FILE="$2"
    if [ -z "$KEY_FILE" ] || [ ! -f "$KEY_FILE" ]; then
      echo "Usage: bash scripts/deploy.sh setup-secrets path/to/key.json"
      exit 1
    fi
    SECRETS="$STREAMLIT_DIR/.streamlit/secrets.toml"
    # Parse key fields from JSON using python
    python3 - "$KEY_FILE" "$SPREADSHEET_ID" "$PI_EMAIL" "$SECRETS" << 'PYEOF'
import json, sys
key_path, spreadsheet_id, pi_email, out_path = sys.argv[1:]
with open(key_path) as f:
    key = json.load(f)

private_key = key['private_key'].replace('\n', '\\n')
lines = [
    f'SPREADSHEET_ID = "{spreadsheet_id}"',
    f'PI_EMAIL = "{pi_email}"',
    '',
    '[gcp_service_account]',
    f'type = "{key["type"]}"',
    f'project_id = "{key["project_id"]}"',
    f'private_key_id = "{key["private_key_id"]}"',
    f'private_key = "{private_key}"',
    f'client_email = "{key["client_email"]}"',
    f'client_id = "{key["client_id"]}"',
    f'auth_uri = "{key["auth_uri"]}"',
    f'token_uri = "{key["token_uri"]}"',
    f'auth_provider_x509_cert_url = "{key["auth_provider_x509_cert_url"]}"',
    f'client_x509_cert_url = "{key["client_x509_cert_url"]}"',
    f'universe_domain = "{key.get("universe_domain", "googleapis.com")}"',
]
with open(out_path, 'w') as f:
    f.write('\n'.join(lines) + '\n')
print(f"✓ Created {out_path}")
PYEOF
    echo "✓ secrets.toml created"
    echo ""
    echo "Next: share the spreadsheet with the service account email:"
    python3 -c "import json; key=json.load(open('$KEY_FILE')); print('  ' + key['client_email'])"
    echo "as Editor at: https://docs.google.com/spreadsheets/d/$SPREADSHEET_ID"
    echo ""
    echo "Then run: bash scripts/deploy.sh setup-sheet"
    ;;

  setup-sheet)
    echo "Sharing spreadsheet and adding Teams sheet + Team column..."
    cd "$STREAMLIT_DIR"
    .venv/bin/python scripts/setup_teams_sheet.py
    echo "✓ Spreadsheet configured"
    echo ""
    echo "Next: run  gh auth login  then  bash scripts/deploy.sh push"
    ;;

  push)
    export PATH="/opt/homebrew/bin:$PATH"
    echo "Setting up GitHub repository..."
    cd "$PROJ_DIR"
    # Check gh is authenticated
    if ! gh auth status &>/dev/null; then
      echo "Not authenticated with GitHub. Run: gh auth login"
      exit 1
    fi
    # Create repo if it doesn't exist
    if ! gh repo view "$GITHUB_REPO" &>/dev/null 2>&1; then
      gh repo create "$GITHUB_REPO" --private --source=. --remote=origin --push
      echo "✓ Created and pushed to github.com/$(gh api user --jq .login)/$GITHUB_REPO"
    else
      OWNER=$(gh api user --jq .login)
      git remote set-url origin "https://github.com/$OWNER/$GITHUB_REPO.git" 2>/dev/null || \
        git remote add origin "https://github.com/$OWNER/$GITHUB_REPO.git"
      git push -u origin main
      echo "✓ Pushed to github.com/$OWNER/$GITHUB_REPO"
    fi
    OWNER=$(gh api user --jq .login)
    echo ""
    echo "============================================"
    echo "FINAL STEP: Deploy on Streamlit Community Cloud"
    echo "============================================"
    echo ""
    echo "1. Go to: https://share.streamlit.io"
    echo "2. Sign in with your Google account"
    echo "3. Click 'New app'"
    echo "4. Repository: $OWNER/$GITHUB_REPO"
    echo "5. Branch: main"
    echo "6. Main file path: streamlit_app/app.py"
    echo "7. Click 'Advanced settings'"
    echo "8. Paste the contents of this file into the Secrets box:"
    echo "     $STREAMLIT_DIR/.streamlit/secrets.toml"
    echo "9. Set Python version to: 3.12"
    echo "10. Click Deploy"
    echo "11. After deploy: Settings → Sharing → Enable password protection"
    echo ""
    echo "Then share the URL + password with lab members."
    ;;

  help|*)
    echo "Usage: bash scripts/deploy.sh <command>"
    echo ""
    echo "Commands:"
    echo "  setup-secrets path/to/key.json   Convert GCP JSON key to secrets.toml"
    echo "  setup-sheet                       Add Teams sheet + Team column to spreadsheet"
    echo "  push                              Create GitHub repo and push code"
    echo ""
    echo "Run them in this order:"
    echo "  1. [Browser] GCP service account setup → download key.json"
    echo "  2. bash scripts/deploy.sh setup-secrets ~/Downloads/key.json"
    echo "  3. [Browser] Share spreadsheet with service account email"
    echo "  4. bash scripts/deploy.sh setup-sheet"
    echo "  5. gh auth login  (browser once)"
    echo "  6. bash scripts/deploy.sh push"
    echo "  7. [Browser] Streamlit Community Cloud deploy (see output of push)"
    ;;
esac
