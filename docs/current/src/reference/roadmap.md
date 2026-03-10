# Roadmap

Project milestones and objectives are tracked in GitHub Projects.

## Current State

The project scaffold is in place with:

- devenv environment with PostgreSQL (AGE, pg_cron) and Kerberos KDC
- 7 ASF component submodules on `rch/signals` branches
- BDD feature specifications for all 6 scenarios (placeholder step definitions)
- Infrastructure scaffolding across 4 deployment modes
- mdbook documentation with GitHub Pages deployment

## Scenario Tiers

Scenarios are organized by implementation tier, indicating the order of development:

| Tier | Focus | Prerequisites |
|------|-------|---------------|
| **Tier 0** | Extension packaging, devenv validation | None |
| **Tier 1** | PostgreSQL, Kerberos integration | devenv services |
| **Tier 2** | gRPC engine, extension deployment, self-improvement | Engine binary |
| **Tier 3** | Full visualization pipeline, analytics scenarios | Engine + Dask + Datashader |
