import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
API_DOC = (ROOT / "docs/api.md").read_text(encoding="utf-8")
CONFIG_DOC = (ROOT / "docs/configuration.md").read_text(encoding="utf-8")


def test_documentation_links_resolve():
    for document in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        body = document.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", body):
            if "://" in target or target.startswith("#"):
                continue
            assert (document.parent / target.split("#", 1)[0]).resolve().exists(), (
                f"Enlace roto en {document.relative_to(ROOT)}: {target}"
            )


def test_all_flask_routes_are_listed_in_api_reference():
    routes = (ROOT / "src/app/routes.py").read_text(encoding="utf-8")
    documented_text = API_DOC.replace("{", "<").replace("}", ">")
    for route in re.findall(r"@main_bp\.route\(['\"]([^'\"]+)", routes):
        assert route in documented_text, f"Ruta sin documentar: {route}"


def test_all_application_environment_variables_are_documented():
    config = (ROOT / "src/app/config.py").read_text(encoding="utf-8")
    variables = set(re.findall(r"os\.environ\.get\(['\"]([A-Z0-9_]+)", config))
    for variable in variables:
        assert f"`{variable}`" in CONFIG_DOC, f"Variable sin documentar: {variable}"


def test_env_example_variables_are_documented():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    variables = set(re.findall(r"^([A-Z0-9_]+)=", env_example, re.MULTILINE))
    for variable in variables:
        assert f"`{variable}`" in CONFIG_DOC, f"Variable de .env.example sin documentar: {variable}"


def test_env_example_variables_are_consumed_by_compose():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    variables = set(re.findall(r"^([A-Z0-9_]+)=", env_example, re.MULTILINE))
    compose = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("docker-compose.yml", "release/docker-compose.yml")
    )
    for variable in variables:
        assert f"${{{variable}" in compose, f"Variable de .env.example no usada por Compose: {variable}"


def test_release_metadata_is_synchronized():
    version = (ROOT / "src/app/version.txt").read_text(encoding="utf-8").strip()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    development_compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    release_compose = (ROOT / "release/docker-compose.yml").read_text(encoding="utf-8")

    assert f"## {version}" in changelog
    assert f"tscneo/ace-hls-viewer:{version.removeprefix('v')}" in README
    assert "ghcr.io/javinator9889/acexy:0.2.2" in development_compose
    assert "ghcr.io/javinator9889/acexy:0.2.2" in release_compose
    assert "${ACE_HLS_IMAGE:-tscneo/ace-hls-viewer:latest}" in release_compose
    assert not (ROOT / "project_context.txt").exists()
