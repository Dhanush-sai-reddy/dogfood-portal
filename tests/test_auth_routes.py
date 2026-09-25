import re
import threading
import time

import pytest

from app.seed import FIXTURE_TOKENS, JUDGE_A_ID, PARTICIPANT_EMAIL


def _error_line(html):
    """The error paragraph: the part of two login responses allowed to be compared."""
    match = re.search(r'<p class="error"[^>]*>(.*?)</p>', html, re.S)
    assert match is not None, f"no error paragraph in {html!r}"
    return match.group(1)


def test_login_page_renders(live):
    response = live.get("/login")
    assert response.status_code == 200
    assert 'name="password"' in response.text


def test_login_sets_a_cookie_and_redirects(live):
    response = live.post(
        "/login",
        data={"email": PARTICIPANT_EMAIL, "password": "dogfood-demo"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/projects"
    assert "sid=" in response.headers["set-cookie"]


def test_wrong_password_sets_no_cookie_and_gives_200_not_403(live):
    response = live.post(
        "/login",
        data={"email": PARTICIPANT_EMAIL, "password": "wrong"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "set-cookie" not in {key.lower() for key in response.headers}


def test_an_unknown_address_and_a_wrong_password_answer_identically(live):
    """The comparison the name promises, rather than one side of it.

    The bodies differ in exactly one place — the address the caller itself typed,
    which the form echoes back — so the status and the error are compared instead:
    nothing in the response distinguishes a registered address from an unregistered
    one, which is what stops the form doubling as an address book.
    """
    unknown = live.post(
        "/login",
        data={"email": "nobody@example.org", "password": "wrong"},
        follow_redirects=False,
    )
    wrong = live.post(
        "/login",
        data={"email": PARTICIPANT_EMAIL, "password": "wrong"},
        follow_redirects=False,
    )
    malformed = live.post(
        "/login",
        content=b"[1,2]",
        headers={"Content-Type": "application/json"},
        follow_redirects=False,
    )
    assert unknown.status_code == wrong.status_code == malformed.status_code == 200
    assert _error_line(unknown.text) == _error_line(wrong.text) == _error_line(malformed.text)
    assert "do not match" in _error_line(unknown.text)
    assert "set-cookie" not in {key.lower() for key in unknown.headers}
    assert "set-cookie" not in {key.lower() for key in wrong.headers}
    assert "set-cookie" not in {key.lower() for key in malformed.headers}


def test_login_is_case_insensitive_on_email(live):
    response = live.post(
        "/login",
        data={"email": PARTICIPANT_EMAIL.upper(), "password": "dogfood-demo"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_whoami_reports_the_role_stored_on_the_row(live):
    live.cookies.set("sid", FIXTURE_TOKENS["judge_a"])
    response = live.get("/whoami")
    assert response.status_code == 200
    assert response.json() == {
        "id": JUDGE_A_ID,
        "email": "diego.herrera@example.org",
        "role": "judge",
    }
    live.cookies.clear()


def test_whoami_is_401_without_a_session(live):
    assert live.get("/whoami").status_code == 401


def test_the_cookie_is_opaque_and_carries_no_role(live):
    """The whole reason for server-side sessions: nothing readable in the cookie.

    The value is asserted rather than the whole header, and against a user id and
    an `@` as well as a role and a name: a token prefixed with either would still
    satisfy the name-and-role substrings.
    """
    live.cookies.set("sid", FIXTURE_TOKENS["judge_a"])
    assert live.get("/whoami").status_code == 200
    live.cookies.clear()
    login = live.post(
        "/login",
        data={"email": "diego.herrera@example.org", "password": "dogfood-demo"},
        follow_redirects=False,
    )
    cookie = login.headers.get("set-cookie", "")
    assert cookie
    value = cookie.split(";", 1)[0]
    assert "judge" not in value
    assert "diego" not in value
    assert "@" not in value
    assert JUDGE_A_ID not in value


def test_logout_revokes_the_session_row(live):
    live.cookies.set("sid", FIXTURE_TOKENS["participant"])
    assert live.get("/whoami").status_code == 200
    assert live.post("/logout", follow_redirects=False).status_code == 303
    assert live.get("/whoami").status_code == 401
    live.cookies.clear()


def test_the_demo_participant_session_ships_unrevoked(live):
    """The demo participant's session row arrives live, and check 3 logs in as them.

    The name says what is asserted: that seeding left this row unrevoked. Nothing
    here re-revokes it, and `test_logout_revokes_the_session_row` is the test that
    revokes one — a token revoked by an unrelated test would silently break check 3.
    """
    import app.security as security
    from app.models import SessionRow

    with live.factory() as db:
        row = db.query(SessionRow).filter(
            SessionRow.token_hash == security.hash_token(FIXTURE_TOKENS["participant"])
        ).one()
        assert row.revoked is False


def test_the_logged_in_header_names_the_user_and_offers_logout(live):
    """The authenticated half of the shell, which only a session can render.

    `user.name` is the one database-sourced string interpolated into the page, and
    it only arrives if `render` resolved the cookie, so this pins the injection as
    well as the markup.
    """
    live.cookies.set("sid", FIXTURE_TOKENS["participant"])
    body = live.get("/login").text
    assert "Priya1 · participant" in body
    assert 'action="/logout"' in body
    assert 'href="/login"' not in body
    live.cookies.clear()


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"[1,2]", id="array"),
        pytest.param(b"5", id="number"),
        pytest.param(b'"hello"', id="string"),
        pytest.param(b"null", id="null"),
        pytest.param(b"{oops", id="unparseable"),
        pytest.param(b"", id="empty"),
    ],
)
def test_a_json_body_that_is_not_an_object_is_treated_as_a_wrong_password(live, body):
    """A JSON body the login branch cannot read is a failed login, not a crash.

    This is not tidiness. The malformed case has to be indistinguishable from the
    wrong-password case, which is the property the route exists to have, so it is
    handled by construction — the credentials come back empty and fall into the
    same branch as a wrong password — rather than by a second error path that
    happens to produce a similar response.
    """
    response = live.post(
        "/login",
        content=body,
        headers={"Content-Type": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert _error_line(response.text) == "That email and password do not match."
    assert "set-cookie" not in {key.lower() for key in response.headers}


def test_a_json_null_is_not_the_string_none(live):
    """`str(None)` is `"None"`, so coercing without checking would open a hole.

    A user whose address is literally `none` would then be reachable with the
    literal password `None` by posting `{"email": null, "password": null}`. No such
    user is seeded and nothing registers one, but the coercion is the bug and the
    hole is only closed at the coercion, so the user is planted to prove it.
    """
    import app.security as security
    from app.models import User

    with live.factory() as db:
        db.add(
            User(
                id="usr_none",
                email="none",
                name="None",
                password_hash=security.hash_password("None"),
                role="participant",
                org=None,
            )
        )
        db.commit()

    response = live.post(
        "/login",
        content=b'{"email": null, "password": null}',
        headers={"Content-Type": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "set-cookie" not in {key.lower() for key in response.headers}


def test_an_unknown_address_costs_the_same_as_a_known_one(live):
    """Bcrypt on a hash hit only makes the response body identical and the clock
    not: ~600 ms against milliseconds is an account-existence oracle.

    The two are compared as a ratio rather than against a millisecond count, so the
    bound is the machine's own bcrypt speed instead of a number that would be wrong
    on faster hardware — and a skipped verification is two orders of magnitude
    short of any fraction of a hash.
    """
    def elapsed_seconds(email, password):
        start = time.perf_counter()
        response = live.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=False,
        )
        assert response.status_code in (200, 303)
        return time.perf_counter() - start

    hit = elapsed_seconds(PARTICIPANT_EMAIL, "dogfood-demo")
    miss = elapsed_seconds("nobody@example.org", "wrong")
    assert miss >= 0.25 * hit, (
        f"an unknown address answered in {miss * 1000:.0f} ms against "
        f"{hit * 1000:.0f} ms for a known one, which is the oracle"
    )


def test_the_password_hash_is_computed_off_the_event_loop(live, monkeypatch):
    """A blocking bcrypt call inside an `async def` route stalls every other request
    for the length of one hash, and `TestClient` is single-threaded, so wall clock
    proves nothing here.

    The thread does: the route's own inline work runs on the event loop, so
    recording the thread on each side of the `await` is a direct statement that the
    hash is not computed there.
    """
    import app.routers.auth as auth

    seen: dict[str, int] = {}
    real_read = auth.read_credentials
    real_verify = auth.verify_password

    async def spy_read_credentials(request):
        seen["loop"] = threading.get_ident()
        return await real_read(request)

    def spy_verify_password(plain, hashed):
        seen["hash"] = threading.get_ident()
        return real_verify(plain, hashed)

    monkeypatch.setattr(auth, "read_credentials", spy_read_credentials)
    monkeypatch.setattr(auth, "verify_password", spy_verify_password)

    response = live.post(
        "/login",
        data={"email": PARTICIPANT_EMAIL, "password": "dogfood-demo"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert seen["loop"] != seen["hash"], "the hash was computed on the event loop"


def test_login_refuses_a_cross_origin_post(live):
    """The same-origin gate is wired into the route, not just defined.

    Every other login test omits `Origin`, which is the gate's no-op path, so
    nothing else here would notice the call being dropped from the route.
    """
    response = live.post(
        "/login",
        data={"email": PARTICIPANT_EMAIL, "password": "dogfood-demo"},
        headers={"Origin": "https://evil.example", "Host": "testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert "set-cookie" not in {key.lower() for key in response.headers}


def test_logout_refuses_a_cross_origin_post(live):
    """A cross-origin POST that revoked a session would be a CSRF logout."""
    live.cookies.set("sid", FIXTURE_TOKENS["participant"])
    response = live.post(
        "/logout",
        headers={"Origin": "https://evil.example", "Host": "testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert live.get("/whoami").status_code == 200
    live.cookies.clear()
