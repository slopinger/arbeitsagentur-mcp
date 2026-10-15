# arbeitsagentur-mcp development notes

Keep README and these notes current. Follow `/home/slop/CLAUDE.md`.

- Every software change must maintain project-owned Nix flake packaging, a committed lockfile,
  development tools and checks. Export a reusable NixOS module where host/service integration
  applies. Verify package builds and relevant flake checks; document supported commands in README.
