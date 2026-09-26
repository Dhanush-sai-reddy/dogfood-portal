import hashlib
import re
from pathlib import Path

from app.config import REPO_ROOT

HTMX_VERSION = "2.0.10"
HTMX_SHA256 = "71ea67185bfa8c98c39d31717c6fce5d852370fcdfd129db4543774d3145c0de"
CDN = re.compile(r"https?://(unpkg|cdn|jsdelivr|fonts\.googleapis|ajax\.google)", re.I)
ANY_URL = re.compile(r"https?://")
FORM = re.compile(r"<form\b[^>]*>", re.I)
SCANNED_SUFFIXES = {".html", ".css", ".js"}
README = REPO_ROOT / "README.md"
HTMX_URL = "/static/js/htmx.min.js"


def _files(kind: str) -> list[Path]:
    """Glob at call time, never a literal list.

    The template directory grows as the portal does, and a hardcoded list would
    quietly stop covering whatever was added after it was written, which is the
    one failure mode a test like this cannot recover from: it would go on
    reporting that the browser side is offline while skipping the newest page.
    """
    return sorted(
        path
        for path in (REPO_ROOT / "app" / kind).rglob("*")
        if path.is_file() and path.suffix in SCANNED_SUFFIXES
    )


def _offenders(pattern: re.Pattern, kind: str) -> list[str]:
    return [
        f"{path.relative_to(REPO_ROOT)}:{number}"
        for path in _files(kind)
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1)
        if pattern.search(line)
    ]


def test_no_template_or_asset_names_a_cdn():
    found = _offenders(CDN, "templates") + _offenders(CDN, "static")
    assert found == [], f"a browser-side network leak: {found}"


def test_the_readme_points_at_no_cdn():
    """A badge or a screenshot in the docs is a browser-side fetch too, and it is
    the one nobody thinks to check."""
    found = [
        f"{number}"
        for number, line in enumerate(README.read_text().splitlines(), 1)
        if CDN.search(line)
    ]
    assert found == [], f"the README sends the reader's browser somewhere: {found}"


def test_no_shipped_asset_contains_an_absolute_url():
    """Stronger than the host blocklist, and it holds: the vendored htmx build
    has no URL in it, so anything this catches is something we added."""
    found = _offenders(ANY_URL, "static")
    assert found == [], found


def test_htmx_is_the_exact_artifact_we_reviewed():
    path = REPO_ROOT / "app" / "static" / "js" / "htmx.min.js"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == HTMX_SHA256
    assert f'version:"{HTMX_VERSION}"' in path.read_text(errors="replace")


def test_the_static_mount_actually_serves_it(live):
    """A file on disk that the mount 404s is the realistic failure, so ask the
    mount and hash the bytes it hands back rather than trusting the path."""
    response = live.get(HTMX_URL)
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert hashlib.sha256(response.content).hexdigest() == HTMX_SHA256


def test_the_base_template_loads_htmx_from_disk():
    base = (REPO_ROOT / "app" / "templates" / "base.html").read_text()
    assert f'<script src="{HTMX_URL}" defer></script>' in base
    assert "unpkg" not in base and "cdn" not in base.lower()


def test_every_static_path_a_template_asks_for_exists():
    referenced: set[str] = set()
    for path in _files("templates"):
        referenced.update(
            re.findall(r'(?:src|href)="(/static/[^"]+)"', path.read_text())
        )
    assert referenced, "no template loads a local asset, so this test is vacuous"
    missing = sorted(
        ref for ref in referenced
        if not (REPO_ROOT / "app" / ref.lstrip("/")).is_file()
    )
    assert missing == [], missing


def test_the_stylesheet_uses_a_system_font_stack():
    css = (REPO_ROOT / "app" / "static" / "css" / "app.css").read_text()
    assert "system-ui" in css
    assert "@import" not in css
    assert "@font-face" not in css


def test_the_judge_console_still_posts_without_javascript():
    """Every hx-* attribute is an upgrade. The method/action pair is what a
    JS-less browser uses, and a same-origin fetch would have to send a CSRF
    token; the plain form does not."""
    console = (REPO_ROOT / "app" / "templates" / "judge_console.html").read_text()
    assert 'method="post"' in console
    assert 'action="/judge/score"' in console
    assert 'hx-sync="closest form:replace"' in console


def test_the_gallery_filter_still_gets_without_javascript():
    gallery = (REPO_ROOT / "app" / "templates" / "gallery.html").read_text()
    assert 'method="get"' in gallery
    assert 'action="/projects"' in gallery
    assert 'hx-get="/projects"' in gallery
    assert 'id="results"' in gallery


def test_every_form_in_every_template_works_without_javascript():
    """The no-JS guarantee, stated over the whole template directory rather than
    one page: a form that carries only hx-post works until the vendored script
    fails to load, and then it silently does nothing. method and action are what
    a browser uses on its own, so every form has to keep both."""
    for path in _files("templates"):
        for tag in FORM.findall(path.read_text()):
            assert "method=" in tag, f"{path.name}: {tag}"
            assert "action=" in tag, f"{path.name}: {tag}"
