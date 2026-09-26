"""The packaging files, asserted as text.

Every test here reads a file and checks a property of it. Nothing in this module
runs `docker`, so the whole file works on a host with no daemon, in CI, and in
the acceptance environment. The flip side is that a green run says the
Dockerfile and compose file say the right things — it does NOT say the image
builds. `docker build` is a manual step, and its result belongs in the task
report rather than in a test that would be slow where it works and skipped
where it cannot.
"""

import re

import pytest

from app.config import REPO_ROOT

RUNTIME_PACKAGES = (
    "fastapi", "uvicorn", "sqlalchemy", "pydantic", "jinja2", "bcrypt",
    "python-multipart",
)


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text()


@pytest.mark.parametrize("package", RUNTIME_PACKAGES)
def test_every_runtime_dependency_is_version_pinned(package):
    assert re.search(rf"^{re.escape(package)}==[0-9][^\s]*", _read("requirements.txt"), re.M), package


def _pinned_blocks(text: str) -> dict[str, list[str]]:
    """Map every pinned requirement to the --hash lines uv emitted beneath it.

    uv compiles the full transitive closure, so this mapping is longer than the
    seven direct names. That extra length is the closure working, not drift —
    do not assert a line count here."""
    blocks: dict[str, list[str]] = {}
    for line in text.splitlines():
        pinned = re.match(r"^([A-Za-z0-9._-]+)==[^\s]+", line)
        if pinned:
            blocks[pinned.group(1)] = []
        elif line.strip().startswith("--hash=") and blocks:
            blocks[next(reversed(blocks))].append(line.strip())
    return blocks


def test_every_requirement_carries_its_artifact_hashes():
    """A requirement with no hash block is the yanked-artifact hole: a wheel
    swapped on PyPI after the build would install silently."""
    blocks = _pinned_blocks(_read("requirements.txt"))
    assert blocks, "requirements.txt pins nothing"
    for package in RUNTIME_PACKAGES:
        assert package in blocks, f"{package} is not pinned"
    for package, hashes in blocks.items():
        assert hashes, f"{package} has no --hash entry"


def test_the_hashes_cover_more_than_this_machine():
    """--universal is what lets an arm64 judge build the image from one file,
    so every requirement is hashed for artifacts past this machine's platform.

    A pin carrying exactly one hash is the silent platform bug: the lockfile
    looks complete, and the missing wheel is only discovered on the one machine
    that needed it. Asserting the floor per pin catches that; asserting a line
    count would not, because the closure length is not the property at risk.
    """
    blocks = _pinned_blocks(_read("requirements.txt"))
    single = sorted(package for package, hashes in blocks.items() if len(hashes) < 2)
    assert not single, f"hashed for a single artifact, so not portable: {single}"


def test_requirements_in_lists_exactly_the_runtime_packages():
    """requirements.in exists so requirements.txt can be compiled rather than
    hand-edited, which only holds if the loose list stays loose. A pin or an
    eighth name added here and not recompiled is drift the other tests cannot
    see, because they all read the compiled file.
    """
    loose = [
        line.strip() for line in _read("requirements.in").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert loose == sorted(RUNTIME_PACKAGES) or loose == list(RUNTIME_PACKAGES)
    assert not [name for name in loose if "==" in name], loose


def test_the_image_installs_by_hash_and_never_from_source():
    text = _read("Dockerfile")
    assert "--require-hashes" in text
    assert "--only-binary=:all:" in text


def test_the_base_image_is_the_python_the_lockfile_was_compiled_for():
    """The hashes were compiled with --python-version 3.12, so a base image on
    another interpreter would resolve to artifacts the file does not list."""
    base = re.search(r"^FROM\s+(\S+)", _read("Dockerfile"), re.M)
    assert base, "the Dockerfile has no FROM"
    # startswith, so a future digest pin (python:3.12-slim@sha256:...) passes.
    assert base.group(1).startswith("python:3.12-slim")


def test_the_image_runs_as_a_non_root_user_that_owns_its_data_dir():
    text = _read("Dockerfile")
    assert "USER 10001" in text
    assert text.index("chown -R 10001:10001") < text.index("USER 10001")


def test_the_image_serves_on_one_worker():
    command = re.search(r"^CMD \[(.*)\]$", _read("Dockerfile"), re.M)
    assert command, "the Dockerfile has no exec-form CMD"
    assert "--workers" in command.group(1) and '"1"' in command.group(1)


def test_nothing_is_installed_when_the_container_starts():
    _head, separator, command = _read("Dockerfile").partition("\nCMD ")
    assert separator, "no CMD to inspect"
    assert "pip" not in command
    assert "ENTRYPOINT" not in _read("Dockerfile")


def test_the_image_ships_the_fixture_it_seeds_from():
    assert "COPY fixtures.json" in _read("Dockerfile")


def test_compose_publishes_on_localhost_and_names_its_volume():
    text = _read("docker-compose.yml")
    assert '"127.0.0.1:${PORT:-8080}:8080"' in text
    assert "dogfood-data:/data" in text
    assert "sqlite+pysqlite:////data/dogfood.db" in text
    # Anchored to the key rather than the bare substring, so the file can keep
    # the comment that warns against it without tripping its own check.
    assert not re.search(r"^\s*internal:\s*true", text, re.M)


def test_compose_reports_a_broken_boot_instead_of_hiding_it():
    text = _read("docker-compose.yml")
    assert 'restart: "no"' in text
    assert "healthcheck:" in text


def test_the_build_context_excludes_the_git_history_and_the_spec():
    lines = {line.strip() for line in _read(".dockerignore").splitlines() if line.strip()}
    for entry in (".git", ".venv", "__pycache__", "data/", "_spec", "tests", "docs"):
        assert entry in lines, entry
