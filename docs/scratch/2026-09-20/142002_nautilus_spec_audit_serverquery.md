# Nautilus spec audit (lattice) — 2026-09-20

Each project in this workspace should have its Nautilus spec audited after
AgentRTC opened empty while Gaius Status stayed green.

Canonical write-up: `gaius/docs/notes/2026-09-20/142002_nautilus_spec_audit_serverquery.md`

Signals-specific: `config/supervision/signals.textproto` should observe Airflow
3 at `/api/v2/monitor/health` (not `/health`), and must not treat Gaius
coordination MISSTICK (`theta_cycle`, `weekly_signals_summary`) as the hub
being unreachable. `dag.gaius_theta_cycle` is a persistent failure
(`CHANNEL_AGENDA_EVENT`), not briefing. Do not catch up Theta.
