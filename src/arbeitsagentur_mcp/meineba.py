"""Access to the user's own "Meine BA" data (eServices) with a login the user performs themselves.

How the login works (OpenID Connect authorization code flow with PKCE, the same flow the BA web
apps use):

1. `login_start(service)` creates a login link to sso.arbeitsagentur.de for that service's web app.
2. The user opens it in their own browser and signs in there (password + second factor, passkey or
   BundID). Their credentials never pass through this program.
3. The browser ends up on an arbeitsagentur.de address containing `code=...&state=...`. The user
   pastes that address into `login_finish`, which exchanges the one-time code for tokens.

Every BA web app is its own OIDC client, so each service needs its own login. Thanks to single
sign-on in the user's browser, logins after the first one complete without entering anything.
Tokens are kept in a local file readable only by the user and refreshed automatically.

The endpoints below are the ones the BA's web apps call; they are not a documented public API and
response formats may change. Responses are passed through mostly unchanged.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from . import __version__

ISSUER = "https://sso.arbeitsagentur.de/auth/realms/OCP"
AUTH_URL = f"{ISSUER}/protocol/openid-connect/auth"
TOKEN_URL = f"{ISSUER}/protocol/openid-connect/token"
LOGOUT_URL = f"{ISSUER}/protocol/openid-connect/logout"
REST = "https://rest.arbeitsagentur.de"


@dataclass(frozen=True)
class Service:
    key: str
    client_id: str
    redirect_uri: str
    description: str


SERVICES: dict[str, Service] = {s.key: s for s in [
    Service("postfach", "kokos", "https://web.arbeitsagentur.de/post/post-kpf-ui/pd/",
            "Postfach: Nachrichten lesen und an Agentur/Jobcenter schreiben"),
    Service("termine", "ota-online", "https://web.arbeitsagentur.de/portal/termine/pd/",
            "Termine bei Agentur für Arbeit / Jobcenter"),
    Service("verlauf", "verlauf-online", "https://web.arbeitsagentur.de/verlauf/verlauf-ui/pd/",
            "Verlauf: Ereignisse und Dokumente im Kundenkonto"),
    Service("antraege", "aue-online", "https://web.arbeitsagentur.de/aue/antragsuebersicht/pd/",
            "Antragsübersicht: Stand der Anträge (z. B. Arbeitslosengeld)"),
    Service("leistungen", "leist-online", "https://web.arbeitsagentur.de/leist/leist/pd/",
            "Leistungen: bewilligte Leistungen und Zahlungen"),
    Service("jobsuche", "jobboerse-jobsuche", "https://www.arbeitsagentur.de/jobsuche/auth-redirect",
            "Jobsuche: Merkliste mit Notizen/Bewerbungsstatus, gespeicherte Suchen"),
]}

POSTFACH_API = f"{REST}/kokos/kokos-ui-service/pd/v1"
TERMINE_API = f"{REST}/portal/ota-service/pd/v1"
VERLAUF_API = f"{REST}/verlauf/verlauf-ereignis-service/pd/v3"
AUE_API = f"{REST}/aue/api/pd"
LEIST_API = f"{REST}/leist/api/pd/v1"
JOBSUCHE_API = f"{REST}/jobboerse/jobsuche-service"

POSTFACH_FOLDERS = ["erhalten", "gesendet", "entwurf", "geloescht"]
WATCHLIST_STATUSES = ["BEWORBEN", "EINGELADEN", "ZUSAGE", "ABSAGE"]

AUE_LIST_QUERY = """query Vorgangsliste($limit: Int) { vorgaengeMitMetadataV2(limit: $limit) {
  istVorgangslisteVollstaendig vorgaenge { aueVersion name vertrauensniveauBadgeAnzeige
  status { ereignisZeitpunktUtc name aktionErwartetVon kundenHinweisZahl } vorgangsId vorgangsart
  leistung { leistungsart leistungsartAnzeigename leistungsTyp leistungsTypAnzeigename }
  vertretungsInformation { agierender vertreterAnzeigename mitWirkungAuf } } } }"""

AUE_DETAIL_QUERY = """query DetailPage($aueVersion: Int!, $vorgangsId: String!) {
  vorgangByIdV2(aueVersion: $aueVersion, vorgangsId: $vorgangsId) { aueVersion archivUrl name vorgangsId
  vorgangsart aktionen { badgeCount buttonText prioritaet url } dokumente { anzeigename dateiname kategorie url }
  logo { logoDienststellennummer logotyp } status { name aktionErwartetVon beschreibungHtml ereignisZeitpunktUtc
  infoContent { infotextHtml infotextUeberschrift } statusbalken }
  vertretungsInformation { agierender vertreterAnzeigename mitWirkungAuf } vertrauensniveauBadgeAnzeige } }"""


class MeineBAError(RuntimeError):
    pass


class NotLoggedIn(MeineBAError):
    def __init__(self, service: str):
        super().__init__(f"Nicht bei '{service}' angemeldet. Erst meineba_login_start(service='{service}') "
                         "aufrufen, im eigenen Browser anmelden und die Ziel-Adresse an meineba_login_finish geben.")
        self.service = service


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt_claims(token: str) -> dict[str, Any]:
    """Decode the payload of a JWT without verifying it (only used to show expiry and identity)."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


def default_token_path() -> Path:
    env = os.environ.get("ARBEITSAGENTUR_MCP_TOKENS")
    if env:
        return Path(env).expanduser()
    db = os.environ.get("ARBEITSAGENTUR_MCP_DB")
    base = Path(db).expanduser().parent if db else Path(
        os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "arbeitsagentur-mcp"
    return base / "meineba-tokens.json"


class TokenStore:
    """Tokens and pending logins in a JSON file with mode 0600."""

    def __init__(self, path: Path | None = None):
        self.path = path or default_token_path()

    def load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {"tokens": {}, "pending": {}}

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)


class MeineBA:
    def __init__(self, tokens: TokenStore | None = None, client: httpx.AsyncClient | None = None):
        self.tokens = tokens or TokenStore()
        self._client = client or httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": f"arbeitsagentur-mcp/{__version__} (+https://github.com/slopinger/arbeitsagentur-mcp)"},
        )

    # --- login ---------------------------------------------------------------------------

    @staticmethod
    def service(key: str) -> Service:
        try:
            return SERVICES[key]
        except KeyError:
            raise MeineBAError(f"Unknown service {key!r}; use one of {', '.join(SERVICES)}") from None

    def login_start(self, service: str) -> dict[str, Any]:
        svc = self.service(service)
        verifier = _b64url(secrets.token_bytes(32))
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        state = _b64url(secrets.token_bytes(16))
        nonce = _b64url(secrets.token_bytes(16))
        data = self.tokens.load()
        now = time.time()
        data["pending"] = {k: v for k, v in data.get("pending", {}).items() if now - v["created"] < 900}
        data["pending"][state] = {"service": service, "verifier": verifier, "created": now}
        self.tokens.save(data)
        url = AUTH_URL + "?" + urlencode({
            "client_id": svc.client_id, "redirect_uri": svc.redirect_uri, "response_type": "code",
            "scope": "openid", "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })
        return {
            "service": service,
            "login_url": url,
            "instructions": (
                "1. Link im eigenen Browser öffnen und dort bei der Bundesagentur anmelden (Passwort und zweiter "
                "Faktor bzw. BundID werden nur auf sso.arbeitsagentur.de eingegeben). "
                "2. Nach der Anmeldung landet der Browser auf einer arbeitsagentur.de-Seite, deren Adresse "
                "'code=' und 'state=' enthält. Diese komplette Adresse sofort kopieren (der Code ist nur etwa "
                "eine Minute gültig) und an meineba_login_finish übergeben. Die Seite selbst kann eine "
                "Fehlermeldung zeigen, das ist egal."),
        }

    async def login_finish(self, redirect_url: str) -> dict[str, Any]:
        query = parse_qs(urlparse(redirect_url.strip()).query)
        if "error" in query:
            raise MeineBAError(f"Anmeldung abgebrochen: {query.get('error_description', query['error'])[0]}")
        code, state = query.get("code", [None])[0], query.get("state", [None])[0]
        if not code or not state:
            raise MeineBAError("Die Adresse enthält kein 'code' und 'state'. Bitte die vollständige Adresse "
                               "aus der Adresszeile nach der Anmeldung kopieren.")
        data = self.tokens.load()
        pending = data.get("pending", {}).pop(state, None)
        if pending is None:
            raise MeineBAError("Unbekannter oder abgelaufener Anmeldevorgang (state passt nicht). "
                               "Bitte mit meineba_login_start neu beginnen.")
        svc = self.service(pending["service"])
        tok = await self._token_request({
            "grant_type": "authorization_code", "code": code, "redirect_uri": svc.redirect_uri,
            "code_verifier": pending["verifier"], "client_id": svc.client_id, "client_secret": svc.client_id,
        })
        data.setdefault("tokens", {})[svc.key] = tok
        self.tokens.save(data)
        return {"service": svc.key, "logged_in": True, **self._describe(tok)}

    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        try:
            r = await self._client.post(TOKEN_URL, data=form, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise MeineBAError(f"Token-Anfrage fehlgeschlagen: {e}") from e
        if r.status_code != 200:
            try:
                err = r.json()
                msg = f"{err.get('error')}: {err.get('error_description', '')}"
            except ValueError:
                msg = r.text[:200]
            raise MeineBAError(f"Anmeldung abgelehnt (HTTP {r.status_code}): {msg}")
        t = r.json()
        now = time.time()
        return {
            "access_token": t["access_token"],
            "refresh_token": t.get("refresh_token"),
            "id_token": t.get("id_token"),
            "expires_at": now + int(t.get("expires_in", 300)),
            "refresh_expires_at": now + int(t["refresh_expires_in"]) if t.get("refresh_expires_in") else None,
        }

    @staticmethod
    def _describe(tok: dict[str, Any]) -> dict[str, Any]:
        claims = jwt_claims(tok["access_token"])
        now = time.time()
        out: dict[str, Any] = {
            "access_valid_seconds": max(0, int(tok["expires_at"] - now)),
        }
        if tok.get("refresh_expires_at"):
            out["session_valid_seconds"] = max(0, int(tok["refresh_expires_at"] - now))
        for k in ("name", "preferred_username", "acting-on-behalf-of", "acr"):
            if claims.get(k):
                out[k.replace("-", "_")] = claims[k]
        return out

    def status(self) -> dict[str, Any]:
        tokens = self.tokens.load().get("tokens", {})
        now = time.time()
        out = {}
        for key, svc in SERVICES.items():
            tok = tokens.get(key)
            if not tok:
                out[key] = {"logged_in": False, "description": svc.description}
                continue
            alive = tok["expires_at"] > now or (tok.get("refresh_token") and (tok.get("refresh_expires_at") or now + 1) > now)
            out[key] = {"logged_in": bool(alive), "description": svc.description, **self._describe(tok)}
        return out

    async def logout(self, service: str | None = None) -> dict[str, Any]:
        data = self.tokens.load()
        keys = [service] if service else list(data.get("tokens", {}))
        done = []
        for key in keys:
            tok = data.get("tokens", {}).pop(key, None)
            if not tok:
                continue
            svc = self.service(key)
            if tok.get("refresh_token"):
                try:
                    await self._client.post(LOGOUT_URL, data={"client_id": svc.client_id, "client_secret": svc.client_id,
                                                              "refresh_token": tok["refresh_token"]})
                except httpx.HTTPError:
                    pass
            done.append(key)
        self.tokens.save(data)
        return {"logged_out": done}

    async def access_token(self, service: str) -> str:
        data = self.tokens.load()
        tok = data.get("tokens", {}).get(service)
        if not tok:
            raise NotLoggedIn(service)
        if tok["expires_at"] - 30 > time.time():
            return tok["access_token"]
        if not tok.get("refresh_token"):
            raise NotLoggedIn(service)
        svc = self.service(service)
        try:
            new = await self._token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                             "client_id": svc.client_id, "client_secret": svc.client_id})
        except MeineBAError:
            data["tokens"].pop(service, None)
            self.tokens.save(data)
            raise NotLoggedIn(service) from None
        data["tokens"][service] = new
        self.tokens.save(data)
        return new["access_token"]

    # --- API calls -----------------------------------------------------------------------

    async def request(self, service: str, method: str, url: str, *, params: dict[str, Any] | None = None,
                      json_body: Any = None, raw: bool = False) -> Any:
        svc = self.service(service)
        token = await self.access_token(service)
        headers = {"Authorization": f"Bearer {token}", "X-API-Key": svc.client_id,
                   "Correlation-ID": str(uuid.uuid4()), "Accept": "application/json", "Accept-Language": "de-DE"}
        try:
            r = await self._client.request(method, url, params=params, json=json_body, headers=headers)
        except httpx.HTTPError as e:
            raise MeineBAError(f"{method} {url} fehlgeschlagen: {e}") from e
        if r.status_code == 401:
            raise NotLoggedIn(service)
        if r.status_code >= 400:
            raise MeineBAError(f"{method} {url} -> HTTP {r.status_code}: {r.text[:400]}")
        if raw:
            return r
        if not r.content:
            return {"status": r.status_code, "location": r.headers.get("Location")}
        try:
            return r.json()
        except ValueError:
            return {"status": r.status_code, "text": r.text[:4000]}

    # Postfach
    async def postfach_list(self, folder: str = "erhalten") -> Any:
        if folder not in POSTFACH_FOLDERS:
            raise MeineBAError(f"folder must be one of {', '.join(POSTFACH_FOLDERS)}")
        return await self.request("postfach", "GET", f"{POSTFACH_API}/ordner/{folder}/nachrichten")

    async def postfach_read(self, folder: str, message_id: str) -> Any:
        return await self.request("postfach", "GET", f"{POSTFACH_API}/ordner/{folder}/nachrichten/{message_id}")

    async def postfach_attachment(self, folder: str, message_id: str, attachment_id: str, target: Path) -> dict[str, Any]:
        r = await self.request("postfach", "GET",
                               f"{POSTFACH_API}/ordner/{folder}/nachrichten/{message_id}/anhaenge/{attachment_id}", raw=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(r.content)
        return {"saved_to": str(target), "bytes": len(r.content), "content_type": r.headers.get("Content-Type")}

    async def postfach_recipients(self) -> dict[str, Any]:
        """Responsible offices (Agentur/Jobcenter/Familienkasse) and the message topics each accepts."""
        vorbelegung = await self.request("postfach", "GET", f"{POSTFACH_API}/dienststellen/vorbelegung")
        out: dict[str, Any] = {"offices": {}}
        for typ, key in (("AA", "dstVorbelegungSGB3"), ("JC", "dstVorbelegungSGB2"), ("FAMKA", "dstVorbelegungFamka"),
                         ("ZAV", "dstVorbelegungZav")):
            office = (vorbelegung or {}).get(key)
            if not office:
                continue
            entry = {"office": office}
            if office.get("teilnehmend") and office.get("dienststellenNummer"):
                entry["topics"] = await self.request("postfach", "GET",
                                                     f"{POSTFACH_API}/anliegen/{typ}/{office['dienststellenNummer']}")
            out["offices"][typ] = entry
        if not out["offices"]:
            out["raw"] = vorbelegung
        return out

    async def postfach_send(self, *, recipient_id: str, recipient_name: str, topic: str, subject: str, text: str,
                            trust_level: str = "STORK-QAA-Level-1") -> Any:
        body = {"empfaengerId": recipient_id, "empfaengerName": recipient_name, "bezug": topic,
                "vNiveau": trust_level, "betreff": subject, "text": text}
        return await self.request("postfach", "POST", f"{POSTFACH_API}/ordner/senden/nachrichten", json_body=body)

    # Termine
    async def appointments(self, now: str | None = None) -> Any:
        return await self.request("termine", "GET", f"{TERMINE_API}/appointments", params={"now": now} if now else None)

    # Verlauf
    async def history(self, limit: int = 20, before: str | None = None, search: str | None = None,
                      categories: list[str] | None = None) -> Any:
        params: list[tuple[str, str]] = [("limit", str(limit))]
        if before:
            params.append(("vor", before))
        if search:
            params.append(("suche", search))
        for c in categories or []:
            params.append(("kategorien", c))
        return await self.request("verlauf", "GET", f"{VERLAUF_API}/verlauf", params=params)  # type: ignore[arg-type]

    async def history_entry(self, entry_id: str) -> Any:
        return await self.request("verlauf", "GET", f"{VERLAUF_API}/verlauf/{entry_id}")

    # Anträge
    async def applications(self, limit: int = 50) -> Any:
        return await self._graphql(AUE_LIST_QUERY, {"limit": limit})

    async def application(self, vorgangs_id: str, aue_version: int) -> Any:
        return await self._graphql(AUE_DETAIL_QUERY, {"vorgangsId": vorgangs_id, "aueVersion": aue_version})

    async def _graphql(self, query: str, variables: dict[str, Any]) -> Any:
        res = await self.request("antraege", "POST", f"{AUE_API}/graphql",
                                 json_body={"query": query, "variables": variables})
        if isinstance(res, dict) and res.get("errors"):
            raise MeineBAError("GraphQL: " + "; ".join(e.get("message", "?") for e in res["errors"]))
        return res.get("data", res) if isinstance(res, dict) else res

    # Leistungen
    async def benefits(self) -> Any:
        return await self.request("leistungen", "GET", f"{LEIST_API}/leistungen/privatPerson")

    # Jobsuche
    async def watchlist(self) -> Any:
        return await self.request("jobsuche", "GET", f"{JOBSUCHE_API}/pd/v1/vormerkungen/infos")

    async def watchlist_set(self, refnr: str, note: str | None = None, status: str | None = None) -> Any:
        if status is not None and status not in WATCHLIST_STATUSES:
            raise MeineBAError(f"status must be one of {', '.join(WATCHLIST_STATUSES)}")
        body = {k: v for k, v in (("notiz", note), ("bewerbungsstatus", status)) if v is not None}
        enc = base64.b64encode(refnr.strip().encode()).decode()
        return await self.request("jobsuche", "PUT", f"{JOBSUCHE_API}/pd/v1/vormerkungen/{enc}", json_body=body)

    async def watchlist_remove(self, refnr: str) -> Any:
        enc = base64.b64encode(refnr.strip().encode()).decode()
        return await self.request("jobsuche", "DELETE", f"{JOBSUCHE_API}/pd/v1/vormerkungen/{enc}")

    async def saved_searches(self) -> Any:
        return await self.request("jobsuche", "GET", f"{JOBSUCHE_API}/pd/v1/suchauftraege")
