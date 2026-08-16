# data-product.tier-upkeep + YK proxy sentinel

Method FSM: adding → copying → verifying → dropping → settled.
DROP not allowed from verifying.

Flow stub: `signals.flows.tier_upkeep.DataProductTierUpkeep`.
Proxy Job stamp: `config/platform/tier-upkeep-sentinel.yaml` on
`root.platform`, app-id `signals-dataproduct-tier-upkeep`.

`just tier-upkeep` prints the plan (no Impala apply yet).
26 related tests green.
