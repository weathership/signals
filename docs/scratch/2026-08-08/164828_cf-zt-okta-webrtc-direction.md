# CF Zero Trust + Okta/GitHub + WebRTC / omni direction

**Date:** 2026-08-08

## Context

Kerberos-required bootstrap in Signals aligns with constellation authn discipline.
Product and multi-modal agent surfaces need the same rigor at the **edge**.

## Notes taken from sibling projects

### Gaius (in production use of Cloudflare)

- Workers + KV at `gaius.zndx.org` (OAuth callbacks, A2UI, sessions).
- Roadmap (gaius-kb-interop): **GitHub OAuth**, **Okta OIDC**, **Cloudflare Zero
  Trust Access** as unified policy; SPA + **WebRTC** behind that edge.

### synth (early HTTPS; ZT next)

- Multi-client observers require **secure context** for mic/camera (`getUserMedia`).
- Today: Caddy TLS in devenv; cloudflared noted as tunnel alternative.
- WebRTC called out for lower-latency A/V; federation + omni models imply **ZT +
  HTTPS out of the box**, not LAN-CA-only forever.

### Arclight GTM

- “Frictionless zero-trust access” as adoption requirement (tunnels + policy, not
  cert wrestling per laptop).

## Signals doctrine (captured)

Architecture page: `docs/current/src/architecture/identity-and-access.md`

| Outer | Edge ZT + Okta/GitHub |
| Inner data plane | Kerberos (lab required) |
| Authz | Atlas tags → Ranger |

No open multi-modal agent UIs over plain HTTP off localhost; no NOSASL data plane.
