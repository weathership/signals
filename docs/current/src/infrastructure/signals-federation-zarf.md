# signals-federation Zarf package

Dedicated air-gap control-plane package for federation sentinels on RKE2.

| | |
|--|--|
| Path | `zarf/federation/` |
| Package name | `signals-federation` |
| Spec | [minifi_sentinels.md](../../components/signals-protocol/specification/operations/minifi_sentinels.md) |

## Why dedicated

`cybersec-dask` (and the legacy `zarf/zarf.yaml` `signals-360` scaffold) must
**not** own Knative/YuniKorn/MiNiFi lifecycle. Cybersec will **defer to and
adopt** this package’s standards as the full stack lands. Independent converge
avoids coupled tear-downs and version skew.

## Ships

1. Knative Serving (CRDs → controllers, KPA scale-to-zero)  
2. YuniKorn (queues `root.{project}`)  
3. MiNiFi C++ sentinel images + Knative Services  

**Does not ship:** host gRPC engines, Dask, Jupyter, Panel-Viz.

## Converge FSM

`zarf/federation/converge/` — cybersec-pattern Layer A/B catalog (T0–T5 stubs).

```bash
cd zarf/federation && python3 -m converge list
python3 -m converge verify   # fails until detects implemented — expected
```

## Coexistence

Same RKE2 node may run `cybersec-dask` + `signals-federation`. Use disjoint
namespaces (`federation-*`, `knative-serving`, `yunikorn` vs `dask`,
`jupyterhub`, `panel-viz`). Share Zarf registry carefully (disk).

## See also

- [zarf.md](./zarf.md) (legacy notes)  
- [minifi-cpp component](../components/minifi-cpp.md)  
- cybersec: `zarf/AIRGAP-CONVERGE-RUNBOOK.md` (FSM pattern to port)  
