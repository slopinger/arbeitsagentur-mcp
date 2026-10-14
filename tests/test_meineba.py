import base64
import hashlib
import json
import os
import stat
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp import Client

from arbeitsagentur_mcp import meineba as mb
from arbeitsagentur_mcp.server import create_server


def fake_jwt(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


class FakeBA:
    """Minimal stand-in for sso.arbeitsagentur.de and the personal REST endpoints."""

    def __init__(self):
        self.challenges = {}
        self.issued = 0
        self.requests = []
        self.sent = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url == mb.TOKEN_URL:
            form = parse_qs(request.content.decode())
            f = {k: v[0] for k, v in form.items()}
            assert f["client_secret"] == f["client_id"]
            if f["grant_type"] == "authorization_code":
                expected = self.challenges[f["code"]]
                got = base64.urlsafe_b64encode(hashlib.sha256(f["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                if got != expected:
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "PKCE"})
            elif f["grant_type"] == "refresh_token":
                if f["refresh_token"] != "refresh-1":
                    return httpx.Response(400, json={"error": "invalid_grant"})
            self.issued += 1
            token = fake_jwt({"name": "Erika Mustermann", "acting-on-behalf-of": "urn:bafor:step:person:kundennummer:123A456789",
                              "azp": f["client_id"], "n": self.issued})
            return httpx.Response(200, json={"access_token": token, "refresh_token": "refresh-1", "expires_in": 300,
                                             "refresh_expires_in": 1800})
        if url == mb.LOGOUT_URL:
            return httpx.Response(204)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return httpx.Response(401)
        if url.startswith(mb.POSTFACH_API + "/ordner/erhalten/nachrichten"):
            return httpx.Response(200, json=[{"id": "m1", "betreff": "Einladung", "gelesen": False}])
        if url == mb.POSTFACH_API + "/dienststellen/vorbelegung":
            return httpx.Response(200, json={"dstVorbelegungSGB3": {"dienststellenNummer": "12345", "dienststellenName":
                                                                    "Agentur für Arbeit Leipzig", "teilnehmend": True}})
        if url == mb.POSTFACH_API + "/anliegen/AA/12345":
            return httpx.Response(200, json=[{"id": 1, "name": "Arbeitsuche", "subanliegen": [{"name": "Allgemein", "bezug": "AS"}]}])
        if url == mb.POSTFACH_API + "/ordner/senden/nachrichten":
            self.sent.append(json.loads(request.content))
            return httpx.Response(201)
        if url.startswith(mb.TERMINE_API + "/appointments"):
            return httpx.Response(200, json={"appointmentLists": []})
        if url == mb.AUE_API + "/graphql":
            body = json.loads(request.content)
            assert "vorgaengeMitMetadataV2" in body["query"]
            return httpx.Response(200, json={"data": {"vorgaengeMitMetadataV2": {"vorgaenge": []}}})
        if url.startswith(mb.JOBSUCHE_API + "/pd/v1/vormerkungen/"):
            return httpx.Response(204)
        return httpx.Response(404)


@pytest.fixture
def fake(tmp_path):
    f = FakeBA()
    client = httpx.AsyncClient(transport=httpx.MockTransport(f.handler))
    m = mb.MeineBA(tokens=mb.TokenStore(tmp_path / "tokens.json"), client=client)
    return f, m


def simulate_browser_login(fake: FakeBA, login_url: str) -> str:
    """What happens in the user's browser: the SSO redirects back with a code."""
    q = {k: v[0] for k, v in parse_qs(urlparse(login_url).query).items()}
    code = f"code-{len(fake.challenges)}"
    fake.challenges[code] = q["code_challenge"]
    return f"{q['redirect_uri']}?state={q['state']}&session_state=x&iss=y&code={code}"


async def test_login_flow_and_api_headers(fake, tmp_path):
    f, m = fake
    start = m.login_start("postfach")
    q = parse_qs(urlparse(start["login_url"]).query)
    assert q["client_id"] == ["kokos"] and q["code_challenge_method"] == ["S256"]
    assert "password" not in start["login_url"]
    res = await m.login_finish(simulate_browser_login(f, start["login_url"]))
    assert res["logged_in"] and res["name"] == "Erika Mustermann"
    assert stat.S_IMODE(os.stat(tmp_path / "tokens.json").st_mode) == 0o600
    msgs = await m.postfach_list()
    assert msgs[0]["id"] == "m1"
    req = f.requests[-1]
    assert req.headers["X-API-Key"] == "kokos" and req.headers["Authorization"].startswith("Bearer ")
    assert req.headers["Correlation-ID"]


async def test_login_finish_rejects_unknown_state_and_errors(fake):
    f, m = fake
    with pytest.raises(mb.MeineBAError, match="state"):
        await m.login_finish("https://web.arbeitsagentur.de/x?code=abc&state=nope")
    with pytest.raises(mb.MeineBAError, match="code"):
        await m.login_finish("https://web.arbeitsagentur.de/x")
    with pytest.raises(mb.MeineBAError, match="abgebrochen"):
        await m.login_finish("https://web.arbeitsagentur.de/x?error=access_denied&error_description=nope")


async def test_not_logged_in(fake):
    _, m = fake
    with pytest.raises(mb.NotLoggedIn, match="meineba_login_start"):
        await m.appointments()


async def test_refresh_when_expired(fake):
    f, m = fake
    start = m.login_start("termine")
    await m.login_finish(simulate_browser_login(f, start["login_url"]))
    data = m.tokens.load()
    data["tokens"]["termine"]["expires_at"] = time.time() - 10
    m.tokens.save(data)
    await m.appointments("2026-10-14")
    assert f.issued == 2
    assert mb.jwt_claims(m.tokens.load()["tokens"]["termine"]["access_token"])["n"] == 2


async def test_logout(fake):
    f, m = fake
    start = m.login_start("jobsuche")
    await m.login_finish(simulate_browser_login(f, start["login_url"]))
    assert m.status()["jobsuche"]["logged_in"]
    assert (await m.logout())["logged_out"] == ["jobsuche"]
    assert not m.status()["jobsuche"]["logged_in"]


async def test_watchlist_encodes_refnr(fake):
    f, m = fake
    start = m.login_start("jobsuche")
    await m.login_finish(simulate_browser_login(f, start["login_url"]))
    await m.watchlist_set("10001-1000911926-S", note="Anrufen", status="BEWORBEN")
    req = f.requests[-1]
    assert req.method == "PUT" and req.url.path.endswith("/MTAwMDEtMTAwMDkxMTkyNi1T")
    assert json.loads(req.content) == {"notiz": "Anrufen", "bewerbungsstatus": "BEWORBEN"}
    with pytest.raises(mb.MeineBAError):
        await m.watchlist_set("x", status="VIELLEICHT")


async def test_server_send_requires_confirmation(fake, store):
    f, m = fake
    server = create_server(store=store, meineba=m)
    async with Client(server) as c:
        start = await c.call_tool("meineba_login_start", {"service": "postfach"})
        url = start.structured_content["login_url"]
        done = await c.call_tool("meineba_login_finish", {"redirect_url": simulate_browser_login(f, url)})
        assert not done.is_error
        rec = await c.call_tool("meineba_postfach_recipients", {})
        office = rec.structured_content["offices"]["AA"]
        assert office["topics"][0]["subanliegen"][0]["bezug"] == "AS"
        args = {"recipient_id": "12345", "recipient_name": "Agentur für Arbeit Leipzig", "topic": "AS",
                "subject": "Terminverlegung", "text": "Guten Tag ..."}
        preview = await c.call_tool("meineba_postfach_send", args)
        assert preview.structured_content["sent"] is False and f.sent == []
        sent = await c.call_tool("meineba_postfach_send", args | {"confirm": True})
        assert sent.structured_content["sent"] is True
        assert f.sent[0]["empfaengerId"] == "12345" and f.sent[0]["betreff"] == "Terminverlegung"
    assert store.list_correspondence()[0]["channel"] == "eservice"


async def test_server_reports_missing_login(fake, store):
    _, m = fake
    async with Client(create_server(store=store, meineba=m)) as c:
        res = await c.call_tool("meineba_antraege", {})
        assert res.is_error and "meineba_login_start" in res.content[0].text
