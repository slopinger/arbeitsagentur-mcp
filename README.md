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

The logged-in eServices ("Meine BA") have no API; nothing is submitted to the agency. General
information, not legal advice.

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
