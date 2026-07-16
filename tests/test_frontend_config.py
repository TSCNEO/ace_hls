from pathlib import Path

from flask import Flask

from app import routes


STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "app" / "static"
VERSION_FILE = STATIC_DIR.parent / "version.txt"


def test_hls_worker_is_disabled_for_extension_compatibility():
    script = (STATIC_DIR / "script.js").read_text()

    assert "enableWorker: false" in script


def test_frontend_cache_versions_match_application_version():
    version = VERSION_FILE.read_text().strip()
    index = (STATIC_DIR / "index.html").read_text()
    service_worker = (STATIC_DIR / "sw.js").read_text()

    assert f"script.js?v={version}" in index
    assert f"style.css?v={version}" in index
    assert f"acehls-{version}" in service_worker


def test_version_endpoint_is_independent_of_working_directory(tmp_path, monkeypatch):
    app = Flask(__name__)
    monkeypatch.chdir(tmp_path)

    with app.test_request_context('/api/version'):
        response = routes.version()

    assert response.get_json()['version'] == VERSION_FILE.read_text().strip()
