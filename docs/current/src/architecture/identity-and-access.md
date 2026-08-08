# Identity and access (authn → authz)

Signals (and the broader ZNDX constellation) separates **who you are** from
**what you may touch**. There is no product path that skips either layer.

## Layers

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| **Edge / human & agent access** | Cloudflare Zero Trust + IdPs (Okta OIDC, GitHub OAuth) | Reach apps and APIs without “open network + hope” |
| **Cluster / data plane** | Kerberos (lab/devenv required; FQDN SPNs) | Impala, Kudu, and related clients — no NOSASL |
| **Governance metadata** | Apache Atlas | Classifications, types, SoR for “what is this data” |
| **Authorization** | Apache Ranger (tag + resource policies) | Enforce “who may use this table/column/tag” using Atlas tags |

Zero Trust is the **outer door**. Kerberos (or equivalent workload identity in
cloud) is the **inner door** for engines. Atlas + Ranger turn “authenticated”
into “authorized.”

## Precedent: Gaius

Gaius already puts **Cloudflare at the edge**:

- **Workers** on `gaius.zndx.org` — OAuth callbacks, A2UI surfaces, KV sessions
  (`gaius/infra`, `gaius-ui/apps/worker`).
- **IdP direction** (gaius-kb-interop roadmap): GitHub OAuth (developers), Okta
  OIDC (enterprise), unified under **Cloudflare Zero Trust Access** policies
  (group membership, risk signals, SCIM).
- **WebRTC** called out next to the SPA: access-controlled edge first, then
  media client.

That is the house pattern: edge authn (CF Access + IdP) → session/JWT → app
and media planes — not browser → bare port on the lab network.

## Precedent: synth (early HTTPS / secure context)

Synth’s multi-client observer work already hits the hard gate:

- `getUserMedia` (mic/camera) requires a **secure context** (HTTPS) off
  localhost — WebKit/iPad has no exception.
- Today: **Caddy TLS** in devenv for LAN secure context (internal CA).
- Explicit alternative called out: **cloudflared** (atelier-style tunnel) —
  good for remote reach, weaker as a pure LAN story unless paired with Access.
- **WebRTC** is the upgrade path for lower-latency audio/video once the
  observer chain is multi-client.

Early synth adoption is “TLS for observations.” Full product federation of
**audio + video agent observations** (and later omni models) needs **ZT +
HTTPS as the default**, not a late bolt-on.

## WebRTC, omni models, federation

| Capability | Why ZT / robust HTTPS matters |
|------------|-------------------------------|
| Agent observation of synthesizer chains | Browser sensors + web UI must be secure-context; multi-device observers |
| WebRTC A/V | DTLS/SRTP assumes proper HTTPS origin and stable identity for signaling |
| Nvidia-class **omni** models | Multi-modal streams (A/V + text) across federated sites — cannot run on ad-hoc open ports |
| Signals governance UIs | Atlas/Ranger/Marquez-web and future OL surfaces behind the same edge discipline |

Federation of multi-modal agent features should assume:

1. **Cloudflare Zero Trust** (or equivalent) in front of every human/agent web
   surface.
2. **Okta / GitHub** as IdPs into Access policies.
3. **Kerberos (or cloud IAM)** for service-to-service data plane.
4. **Atlas classifications → Ranger policies** for data authorization.

## Signals today (lab)

| Concern | State |
|---------|--------|
| Bootstrap | `just bootstrap` — Kerberos KDC, keytabs, FQDN, kinit (required) |
| Impala / Kudu | Kerberos only; GSSAPI clients via `signals.impala` |
| Atlas / Ranger | Authz spine; portable SoR via `just backup` / `just restore` |
| Edge ZT | Not yet wired in this repo — adopt Gaius/Access patterns when product UIs leave localhost |

## Non-goals / rejected

- NOSASL or “auth optional” for Impala/Kudu in devenv  
- Shipping multi-modal agent UIs over plain HTTP outside localhost  
- Treating Cloudflare only as CDN without Access policies for app routes  

## Related

- Lab Kerberos: `docs/current/src/operations/storage-and-backup.md`,  
  `scripts/signals_kerberos.sh`, `just bootstrap`  
- Gaius edge: `gaius/infra`, `gaius-ui/apps/worker`  
- Gaius IdP roadmap: `gaius-kb-interop/design` (Okta + Zero Trust + WebRTC)  
- Synth secure context: `synth` docs on multi-client observers + Caddy TLS  
- Arclight GTM: frictionless zero-trust access as adoption requirement  
