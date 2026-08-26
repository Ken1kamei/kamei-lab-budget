import io
import json
from types import SimpleNamespace

import pytest
from django.core.management import call_command

from budget.services.calculations import snapshot_totals


@pytest.mark.django_db
def test_verify_planned_roundtrip_writes_reads_and_removes_dummy(
    settings, monkeypatch
):
    settings.ENABLE_SHEET_WRITES = True

    class Gateway:
        row = None

        def read_fiscal_year(self, fiscal_year):
            return {
                "fiscal_year": fiscal_year,
                "summary": [
                    {"Category": "Other", "Budgeted (USD equiv)": "100"}
                ],
                "teams": [
                    {
                        "Team Name": "Core Lab",
                        "Allocation (USD)": "100",
                        "Active": "Y",
                    }
                ],
                "transactions": [self.row] if self.row else [],
            }

        def write_transaction(
            self, fiscal_year, payload, transaction_id="", allow_existing=False
        ):
            assert payload["status"] == "Planned"
            assert allow_existing is True
            self.row = {
                "Transaction ID": transaction_id,
                "Category": payload["category"],
                "Team": payload["team"],
                "Status": payload["status"],
                "Currency": payload["currency"],
                "Amount": str(payload["amount"]),
            }
            return {"transaction_id": transaction_id, "row": self.row}

        def delete_transaction(self, fiscal_year, transaction_id):
            assert self.row["Transaction ID"] == transaction_id
            self.row = None
            return True

    gateway = Gateway()
    command_path = "budget.management.commands.verify_planned_roundtrip"
    monkeypatch.setattr(f"{command_path}.SheetsGateway", lambda: gateway)
    monkeypatch.setattr(
        f"{command_path}.sync_fiscal_year",
        lambda snapshot, actor: SimpleNamespace(status="matched", fiscal_year=object()),
    )
    monkeypatch.setattr(
        f"{command_path}.database_totals",
        lambda fiscal_year: snapshot_totals(gateway.read_fiscal_year("FY2026-27")),
    )
    output = io.StringIO()

    call_command(
        "verify_planned_roundtrip",
        fiscal_year="FY2026-27",
        team="Core Lab",
        stdout=output,
    )

    evidence = json.loads(output.getvalue())
    assert evidence["sheet_status"] == "Planned"
    assert evidence["planned_during"] == "0.01"
    assert evidence["available_delta"] == "-0.01"
    assert evidence["restored"] is True
    assert gateway.row is None
