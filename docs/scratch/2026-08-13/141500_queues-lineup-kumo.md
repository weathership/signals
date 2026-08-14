# Queues: Aegir lineup + Kumo children

**Date:** 2026-08-13

## UX

- **Lineup trail** (horizontal panels, Aegir-style): panel 1 = root Queue Info.
- **Kumo cards** list children; click opens next panel with that queue’s info.
- Close (×) walks back to parent; **Reset to root** clears path.
- Dark Keiretsu / Atelier palette unchanged.
- Queue Info fields align with yk-web (Name, Status, Allocated/Pending/Max/Guaranteed
  resource lines, Absolute Used Capacity, app counts).

## Code

- `build_lineup_trail` + rich `resource_lines` / `abs_used_lines` in `main.rs`
- `queues.html` + `shell.css` lineup panel styles
- URL: `/queues?partition=default&queue=root.signals` deepens trail

## Verify

```bash
curl -s 'http://127.0.0.1:9889/queues?partition=default' | rg '3\.71 GiB|Children'
curl -s 'http://127.0.0.1:9889/queues?partition=default&queue=root.default' | rg 'panel 2|Open applications'
```
