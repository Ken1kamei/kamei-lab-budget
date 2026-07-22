from budget.services.sheets import SheetsGateway


class Worksheet:
    def __init__(self, values=None, records=None):
        self.values = values or []
        self.records = records or []

    def get_all_values(self):
        return self.values

    def get_all_records(self):
        return self.records


class Workbook:
    def __init__(self, sheets):
        self.sheets = sheets

    def worksheet(self, name):
        return self.sheets[name]


class Client:
    def __init__(self, books):
        self.books = books

    def open_by_key(self, key):
        return self.books[key]


def test_gateway_reads_dedicated_year_and_filters_blank_transaction_ids(settings, monkeypatch):
    settings.MASTER_SPREADSHEET_ID = "master"
    settings.REGISTRY_SPREADSHEET_ID = ""
    master = Workbook(
        {
            "Config": Worksheet(
                values=[
                    ["Current Fiscal Year", "FY2025-26"],
                    ["Spreadsheet ID FY2026-27", "fy-2026"],
                ]
            )
        }
    )
    annual = Workbook(
        {
            "Transactions": Worksheet(
                records=[
                    {"Transaction ID": "TXN-1", "Amount (USD equiv)": "10"},
                    {"Transaction ID": "", "Amount (USD equiv)": "999"},
                ]
            ),
            "Summary": Worksheet(values=[["Consumables", "", "", "1000"]]),
            "Teams": Worksheet(records=[]),
            "Config": Worksheet(values=[["AED/USD Exchange Rate", "3.5"]]),
        }
    )
    gateway = SheetsGateway(client=Client({"master": master, "fy-2026": annual}))
    monkeypatch.setattr("budget.services.sheets._legacy_secrets", lambda: {})

    snapshot = gateway.read_fiscal_year("FY2026-27")

    assert snapshot["spreadsheet_id"] == "fy-2026"
    assert [row["Transaction ID"] for row in snapshot["transactions"]] == ["TXN-1"]
    assert snapshot["summary"][0]["Budgeted (AED equiv)"] == "1000"
    assert snapshot["aed_per_usd"] == "3.5"
