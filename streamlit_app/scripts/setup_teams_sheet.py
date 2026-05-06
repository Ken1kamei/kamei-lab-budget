"""One-time script: adds Teams tab and Team column to the existing spreadsheet."""
import json, sys
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://spreadsheets.google.com/feeds",
          "https://www.googleapis.com/auth/drive"]

def load_secrets():
    secrets_path = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(secrets_path, "rb") as f:
        return tomllib.load(f)

def main():
    secrets = load_secrets()
    creds = Credentials.from_service_account_info(
        secrets["gcp_service_account"], scopes=SCOPES)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(secrets["SPREADSHEET_ID"])

    # 1. Add Teams sheet if not present
    sheet_names = [s.title for s in ss.worksheets()]
    if "Teams" not in sheet_names:
        teams_sheet = ss.add_worksheet("Teams", rows=50, cols=6)
        headers = ["Team Name", "Allocation (AED)", "Lead Emails",
                   "Member Emails", "Description", "Active"]
        teams_sheet.append_row(headers)
        # Format header row purple
        teams_sheet.format("A1:F1", {
            "backgroundColor": {"red": 0.341, "green": 0.024, "blue": 0.549},
            "textFormat": {"foregroundColor": {"red":1,"green":1,"blue":1},
                           "bold": True}
        })
        print("✓ Created Teams sheet")
    else:
        print("  Teams sheet already exists, skipping")

    # 2. Add lifecycle columns to Transactions if not present
    txn_sheet = ss.worksheet("Transactions")
    headers = txn_sheet.row_values(1)
    for header in ["Team", "Approved By", "Approved At"]:
        if header in headers:
            print(f"  {header} column already exists, skipping")
            continue
        next_col = len(headers) + 1
        txn_sheet.update_cell(1, next_col, header)
        headers.append(header)
        # Format new header cell
        col_letter = chr(64 + next_col)
        txn_sheet.format(f"{col_letter}1", {
            "backgroundColor": {"red": 0.341, "green": 0.024, "blue": 0.549},
            "textFormat": {"foregroundColor": {"red":1,"green":1,"blue":1},
                           "bold": True}
        })
        print(f"✓ Added '{header}' column at column {next_col} of Transactions sheet")

    print("\nSetup complete.")

if __name__ == "__main__":
    main()
