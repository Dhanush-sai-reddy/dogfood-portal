"""Acceptance tests for the organizer checker."""

import os
import sys
import subprocess
import time
import tempfile
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.main import create_app
from tests.test_deps_isolation import _iter_routes


def _config():
    """Load the .dogfood.toml config the checker expects."""
    import tomllib
    with open(REPO_ROOT / ".dogfood.toml", "rb") as f:
        return tomllib.load(f)


def _effective_paths(app):
    """All effective paths from included routers, same logic as isolation test."""
    paths = set()
    for route in app.routes:
        for path, _ in _iter_routes([route]):
            if path:
                paths.add(path)
    return paths


def test_the_vendored_checker_is_byte_identical_to_the_organizers():
    """run.py must not be modified."""
    with open(REPO_ROOT / "run.py", "rb") as f:
        our = f.read()
    with open(REPO_ROOT / "_spec" / "run.py", "rb") as f:
        spec = f.read()
    assert our == spec, "run.py differs from organizer's version"


def test_the_vendored_fixtures_are_byte_identical_to_the_organizers():
    """fixtures.json must not be modified."""
    with open(REPO_ROOT / "fixtures.json", "rb") as f:
        our = f.read()
    with open(REPO_ROOT / "_spec" / "fixtures.json", "rb") as f:
        spec = f.read()
    assert our == spec, "fixtures.json differs from organizer's version"


def test_every_configured_route_exists_on_the_app():
    """Every route in .dogfood.toml must be registered."""
    cfg = _config()
    app = create_app()
    paths = _effective_paths(app)
    missing = {
        key: value
        for key, value in cfg["routes"].items()
        if value.split("?")[0] not in paths
    }
    assert missing == {}, f"configured but not routed: {missing}"


def test_every_configured_auth_value_is_a_seeded_session():
    """Every auth header in .dogfood.toml must match a fixture token."""
    cfg = _config()
    fixture_tokens = {
        "tok_organizer_7f3a91c2",
        "tok_judge_a_91bc44de",
        "tok_judge_b_44de91bc",
        "tok_participant_2e88prt0",
    }
    for role, header in cfg["auth"].items():
        token = header.split("sid=")[-1] if "sid=" in header else header
        assert token in fixture_tokens, f"unknown auth token for {role}: {header}"


def test_the_peer_probe_is_another_judges_scores():
    """The peer probe URL must use a different judge id."""
    cfg = _config()
    peer = cfg["routes"]["peer_scores"]
    own = cfg["routes"]["judge_scores"]
    assert peer != own, "peer_scores must differ from judge_scores"
    assert "judge=" in peer, "peer_scores must contain a judge query param"


def test_claimed_never_runs_ahead_of_what_the_checker_tests():
    """.dogfood.toml claims only T1 and T2."""
    cfg = _config()
    assert cfg.get("tiers", {}).get("claimed") == ["T1", "T2"], f"unexpected claims: {cfg.get('tiers', {}).get('claimed')}"


def _wait_for_port_file(path: Path, process: subprocess.Popen) -> str:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if path.exists():
            url = path.read_text().strip()
            if url:
                return url
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"the portal process died:\n{output}")
        time.sleep(0.1)
    raise AssertionError("timed out waiting for portal port file")


@pytest.fixture
def portal(tmp_path):
    """A real server on a real port, backed by a throwaway database."""
    port_file = tmp_path / "url"
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "DOGFOOD_DATABASE_URL": f"sqlite+pysqlite:///{tmp_path / 'acceptance.db'}",
        "DOGFOOD_FIXTURES": str(REPO_ROOT / "fixtures.json"),
    }
    process = subprocess.Popen(
        [sys.executable, "tests/_acceptance_server.py", str(port_file)],
        cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        yield _wait_for_port_file(port_file, process)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        (tmp_path / "acceptance.db").unlink(missing_ok=True)


def test_the_organizers_own_checker_reports_7_of_7(portal):
    """The organizer checker must report 7 PASS."""
    # Read the base config and update base_url to the portal's URL via string replace
    with open(REPO_ROOT / ".dogfood.toml", "r") as f:
        config_text = f.read()
    
    # Replace base_url line
    config_text = re.sub(
        r'base_url\s*=\s*".*?"',
        f'base_url = "{portal.rstrip("/")}"',
        config_text
    )
    
    # Write temp config
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as tf:
        tf.write(config_text)
        temp_config = tf.name
    
    try:
        env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
        result = subprocess.run(
            [sys.executable, "run.py", temp_config],
            cwd=REPO_ROOT, capture_output=True, text=True, env=env, timeout=60,
        )
    finally:
        os.unlink(temp_config)
    
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    assert result.returncode == 0, f"checker exited {result.returncode}: {result.stderr}"
    assert "verified T1 T2" in result.stdout, f"expected 7 PASS, got:\n{result.stdout}"
