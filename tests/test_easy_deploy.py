from pathlib import Path
from zipfile import ZipFile

from scripts.package_easy_deploy import PACKAGE_FILES, create_archive, read_version


ROOT = Path(__file__).resolve().parents[1]
EASY_DEPLOY = ROOT / "easy-deploy"
LOCAL_COMPOSE = EASY_DEPLOY / "orchestrator-local/compose.yml"
REMOTE_COMPOSE = EASY_DEPLOY / "orchestrator-remote/compose.yml"


def test_easy_deploy_uses_versioned_images_without_build():
    image = f"tscneo/ace-hls-viewer:{read_version().removeprefix('v')}"
    for compose_path in (LOCAL_COMPOSE, REMOTE_COMPOSE):
        compose = compose_path.read_text(encoding="utf-8")
        assert image in compose
        assert "ace-hls-viewer:latest" not in compose
        assert "build:" not in compose
        assert "acexy" not in compose.lower()


def test_easy_deploy_variants_share_stable_ace_hls_volume():
    for compose_path in (LOCAL_COMPOSE, REMOTE_COMPOSE):
        compose = compose_path.read_text(encoding="utf-8")
        assert "name: ${ACE_HLS_DATA_VOLUME:-ace_hls_data}" in compose


def test_remote_easy_deploy_does_not_manage_local_services():
    compose = REMOTE_COMPOSE.read_text(encoding="utf-8")
    assert "  orchestrator:" not in compose
    assert "/var/run/docker.sock" not in compose
    assert "orchestrator_data" not in compose
    assert "ORCHESTRATOR_HOST:?Define ORCHESTRATOR_HOST" in compose


def test_archive_is_complete_and_reproducible(tmp_path):
    first = create_archive(tmp_path / "first")
    second = create_archive(tmp_path / "second")
    version = read_version()
    package_name = f"ace-hls-easy-deploy-{version}"
    expected = {
        f"{package_name}/{path.as_posix()}" for path in PACKAGE_FILES
    } | {f"{package_name}/VERSION"}

    assert first.name == f"{package_name}.zip"
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        assert set(archive.namelist()) == expected
        assert archive.read(f"{package_name}/VERSION").decode() == f"{version}\n"
        assert not any(name.endswith("/.env") for name in archive.namelist())


def test_examples_only_contain_documented_placeholder_token():
    for env_path in EASY_DEPLOY.glob("*/.env.example"):
        env = env_path.read_text(encoding="utf-8")
        assert "ORCHESTRATOR_API_TOKEN=cambia-este-token-compartido" in env
        assert "defaultpassword" not in env
        assert "change-this-local-token" not in env


def test_stable_tag_workflow_never_publishes_dev_prereleases():
    workflow = (ROOT / ".github/workflows/easy-deploy-release.yml").read_text(
        encoding="utf-8"
    )
    assert "!contains(github.ref_name, '-')" in workflow
    assert "docker buildx imagetools inspect" in workflow
    assert "python scripts/package_easy_deploy.py" in workflow
    assert "gh release create" in workflow
