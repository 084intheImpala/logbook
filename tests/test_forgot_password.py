"""Forgot password: a one-time login link is e-mailed, and it logs the user in."""
import pytest

import backend.email_utils


@pytest.fixture
def sent(monkeypatch):
    mails = []

    async def fake_send(to, username, magic_link):
        mails.append(dict(to=to, username=username, link=magic_link))
    monkeypatch.setattr(backend.email_utils, "send_password_reset_email", fake_send)
    return mails


def test_reset_link_is_sent_and_logs_in(world, sent):
    user = world.user("forgetful")
    anon = world.client(None)
    r = anon.post("/forgot-password", data={"email": user.email.upper()})
    assert r.status_code == 200
    (mail,) = sent
    assert mail["to"] == user.email and mail["username"] == user.username
    token = mail["link"].split("token=")[1]
    r = anon.get(f"/magic?token={token}")
    assert r.status_code == 303 and r.headers["location"] == "/change-password"
    assert anon.get(f"/magic?token={token}").status_code == 400   # used once only


def test_unknown_address_looks_the_same(world, sent):
    r = world.client(None).post("/forgot-password", data={"email": "nobody@example.org"})
    assert r.status_code == 200 and not sent
