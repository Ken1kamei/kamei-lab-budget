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
