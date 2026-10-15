# arbeitsagentur-mcp

MCP server for **customers** of the German Bundesagentur für Arbeit (Agentur für Arbeit / Jobcenter).

- **Live public data** (no login): Jobbörse search and job ads, Weiterbildungssuche (mein NOW / KURSNET),
  BERUFENET occupation profiles, Entgeltatlas salaries, Dienststellen finder.
- **Local case file** (SQLite, mode 0600, never leaves your machine): profile, applications /
  Eigenbemühungen with *Nachweis* export (Markdown/CSV), Vermittlungsvorschläge, appointments,
  correspondence with automatic Widerspruch deadlines, tasks, `overview` dashboard.
- **Deadline calculators**: Widerspruch (§ 84 SGG, § 37 SGB X incl. the 4-day rule since 2025),
  Arbeitsuchend-/Arbeitslosmeldung (§§ 38, 141 SGB III), generic periods with weekend/holiday shift
  for all Bundesländer, ALG duration (§ 147 SGB III).
- **Letter drafts**: Widerspruch, Akteneinsicht/DSGVO, Überprüfungsantrag, Veränderungsmitteilung,
  Terminabsage, Krankmeldung, Rückmeldung Vermittlungsvorschlag, Bildungsgutschein, Ortsabwesenheit.
- `rules` tool with short, sourced explanations of duties and sanctions.
- **Your own "Meine BA" account** (`meineba_*`): Postfach (read, download attachments, send after
  explicit confirmation), Termine, Verlauf, Antragsübersicht, Leistungen, Jobsuche watch list with
  notes and application status, saved searches.

General information, not legal advice.

## Meine BA login

You sign in yourself; the server never sees your password.

1. `meineba_login_start(service="postfach")` returns a link to `sso.arbeitsagentur.de`.
2. Open it in your own browser and sign in (password + second factor, passkey or BundID).
3. The browser lands on an arbeitsagentur.de page whose address contains `code=…&state=…` (the page
   itself may show an error; that's fine). Copy the full address within about a minute and pass it
   to `meineba_login_finish`.

This is the OpenID Connect authorization-code flow with PKCE that the BA web apps use. Each BA web
app is its own client (`postfach`, `termine`, `verlauf`, `antraege`, `leistungen`, `jobsuche`), so each
needs a login; after the first one your browser's single sign-on makes the others instant. Tokens are
stored in `meineba-tokens.json` next to the case file (mode 0600, override with
`ARBEITSAGENTUR_MCP_TOKENS`) and refreshed automatically; `meineba_logout` ends the sessions.

The endpoints are the ones the BA's own web apps call, not a documented API. They were mapped from
the apps' public JavaScript and checked to exist, and the client is tested against a simulated SSO
and API, but response formats can differ or change; responses are passed through mostly as-is.

## Usage

```sh
uv run arbeitsagentur-mcp            # stdio
claude mcp add arbeitsagentur -- uv --directory /path/to/arbeitsagentur-mcp run arbeitsagentur-mcp
```

Options: `--db PATH` (or `ARBEITSAGENTUR_MCP_DB`; default `~/.local/share/arbeitsagentur-mcp/akte.sqlite3`),
`--transport streamable-http --host 127.0.0.1 --port 8000`.

## Tests

```sh
uv run pytest            # offline
uv run pytest -m live    # against the real APIs
```

The public endpoints and client IDs are those used by the BA's own web apps (see bundesAPI on GitHub).
License: MIT.

## Nix packaging

`nix build` builds the `arbeitsagentur-mcp` executable and its Python runtime from
`uv.lock` using uv2nix. `nix run . -- --help` shows the CLI. No network access
is required when running the application build after its pinned inputs have
been fetched. `nix flake check` runs the offline test suite (56 tests at
introduction); live directory/API requests are excluded. Linux x86_64 and
aarch64 packages are defined; builds were verified on x86_64.

`nix develop` provides an editable Python environment plus uv. Run `pytest` or
`arbeitsagentur-mcp` directly there; changes under `src/` take effect immediately.
Run `uv lock` when changing Python dependencies and commit `uv.lock`; update
Nix inputs with `nix flake update` and commit `flake.lock`.

This project is a per-user stdio tool by default. It has no NixOS service module;
there is no public authenticated HTTP deployment. Private databases and user
configuration stay outside the Nix store and repository at the paths documented
above.
