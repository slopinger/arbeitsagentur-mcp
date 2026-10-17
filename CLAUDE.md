# arbeitsagentur-mcp development notes

Keep README and these notes current. Follow `/home/slop/CLAUDE.md`.

- Python/uv MCP server for Bundesagentur für Arbeit customers: public BA data (Jobbörse, Weiterbildung,
  Berufenet, Entgeltatlas), a private local case file, deadline calculators, letter drafts and the
  user's own "Meine BA" account. README documents every tool.
- Run `uv run arbeitsagentur-mcp` (stdio). Checks: `uv run pytest` (offline), `uv run pytest -m live`
  (real APIs), `uv build`.
- Private data: case file `~/.local/share/arbeitsagentur-mcp/akte.sqlite3` (`--db` /
  `ARBEITSAGENTUR_MCP_DB`), Meine BA tokens in `meineba-tokens.json` next to it (`ARBEITSAGENTUR_MCP_TOKENS`),
  both 0600. Never commit them or put case data into public searches, and never mix it with the
  separate therapie-mcp workflow. The user logs in to Meine BA themselves; sending a Postfach message
  needs their explicit confirmation of the exact text.
- Signed small commits, pushed to https://github.com/slopinger/arbeitsagentur-mcp (`git push origin main`).

- Every software change must maintain project-owned Nix flake packaging, a committed lockfile,
  development tools and checks. Export a reusable NixOS module where host/service integration
  applies. Verify package builds and relevant flake checks; document supported commands in README.

- Nix: `nix build`, `nix flake check`, `nix develop`; commit `flake.lock`.
  uv2nix consumes `uv.lock`; the dev shell is editable. Run `pytest` directly in it.
  The per-user stdio tool has no public service module. Keep private data out of the store.
- Never add Co-Authored-By trailers or session links to public GitHub content.
