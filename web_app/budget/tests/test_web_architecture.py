from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_production_image_does_not_copy_legacy_app():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8").casefold()

    assert "streamlit" not in dockerfile
    assert "copy web_app/" in dockerfile


def test_web_runtime_does_not_reference_legacy_app():
    runtime_roots = [
        REPO_ROOT / "web_app" / "budget",
        REPO_ROOT / "web_app" / "labapps",
        REPO_ROOT / "web_app" / "config",
        REPO_ROOT / "web_app" / "templates",
    ]
    offenders = []
    for root in runtime_roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".html"}:
                continue
            if "tests" in path.parts:
                continue
            if "streamlit" in path.read_text(encoding="utf-8").casefold():
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []


def test_cloud_source_rebuilds_portal_integration_static_assets():
    cloudignore = {
        line.strip().rstrip("/")
        for line in (REPO_ROOT / "web_app" / ".gcloudignore").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    portal_css = (
        REPO_ROOT / "web_app" / "budget" / "static" / "budget" / "app.css"
    ).read_text(encoding="utf-8")
    start_script = (REPO_ROOT / "web_app" / "start.sh").read_text(encoding="utf-8")

    assert "staticfiles" in cloudignore
    assert "python manage.py collectstatic --noinput --clear" in start_script
    assert start_script.index("collectstatic") < start_script.index("exec gunicorn")
    assert ".portal-integrations" in portal_css
    assert ".week-calendar" in portal_css
    assert ".slack-messages" in portal_css


def test_sync_job_alignment_uses_the_buildpacks_launcher():
    script = (REPO_ROOT / "scripts" / "align_cloud_run_sync_job.sh").read_text(
        encoding="utf-8"
    )

    assert "--command=/cnb/lifecycle/launcher" in script
    assert "--args=python,manage.py,sync_sheets" in script
    assert "/usr/local/bin/python" not in script
