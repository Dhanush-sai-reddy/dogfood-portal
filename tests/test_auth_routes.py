from app.seed import FIXTURE_TOKENS, JUDGE_A_ID, PARTICIPANT_EMAIL


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


def test_unknown_email_looks_identical_to_a_wrong_password(live):
    response = live.post(
        "/login",
        data={"email": "nobody@example.org", "password": "wrong"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "do not match" in response.text


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
    """The whole reason for server-side sessions: nothing readable in the cookie."""
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
    assert "judge" not in cookie
    assert "diego" not in cookie


def test_logout_revokes_the_session_row(live):
    live.cookies.set("sid", FIXTURE_TOKENS["participant"])
    assert live.get("/whoami").status_code == 200
    assert live.post("/logout", follow_redirects=False).status_code == 303
    assert live.get("/whoami").status_code == 401
    live.cookies.clear()


def test_a_revoked_demo_token_stays_revoked_for_the_checker(live):
    """Logging out as the demo participant would silently break check 3."""
    import app.security as security
    from app.models import SessionRow

    with live.factory() as db:
        row = db.query(SessionRow).filter(
            SessionRow.token_hash == security.hash_token(FIXTURE_TOKENS["participant"])
        ).one()
        assert row.revoked is False


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
