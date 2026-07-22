from django.core.management import call_command


def test_storage_verification_command_restores_local_storage(settings, tmp_path, capsys):
    settings.DEBUG = True
    settings.INVOICE_BUCKET = ""
    settings.INVOICE_STORAGE_PREFIX = "invoices"
    settings.MEDIA_ROOT = tmp_path

    call_command("verify_storage_roundtrip")

    output = capsys.readouterr().out
    assert '"readback_matches": true' in output
    assert '"removed": true' in output
    assert not list(tmp_path.rglob("*.pdf"))
