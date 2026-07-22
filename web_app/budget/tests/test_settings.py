import os
import subprocess
import sys
from pathlib import Path


WEB_APP_ROOT = Path(__file__).resolve().parents[2]


def test_cloud_database_url_overrides_legacy_database_url(tmp_path):
    legacy_db = tmp_path / "legacy.sqlite3"
    cloud_db = tmp_path / "cloud.sqlite3"
    environment = os.environ.copy()
    environment.update(
        {
            "DEBUG": "true",
            "DATABASE_URL": f"sqlite:///{legacy_db}",
            "CLOUD_DATABASE_URL": f"sqlite:///{cloud_db}",
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config.settings import DATABASES; print(DATABASES['default']['NAME'])",
        ],
        cwd=WEB_APP_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == str(cloud_db)
