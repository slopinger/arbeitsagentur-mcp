# arbeitsagentur-mcp development notes

Keep README and these notes current. Follow `/home/slop/CLAUDE.md`.

- Every software change must maintain project-owned Nix flake packaging, a committed lockfile,
  development tools and checks. Export a reusable NixOS module where host/service integration
  applies. Verify package builds and relevant flake checks; document supported commands in README.

- Nix: `nix build`, `nix flake check`, `nix develop`; commit `flake.lock`.
  uv2nix consumes `uv.lock`; the dev shell is editable. Run `pytest` directly in it.
  The per-user stdio tool has no public service module. Keep private data out of the store.
- Never add Co-Authored-By trailers or session links to public GitLab content.
