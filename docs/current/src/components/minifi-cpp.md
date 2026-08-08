# MiNiFi C++ (federation sentinels)

Submodule: `components/minifi-cpp` →
[`git@github.com:weathership/oss-minifi-cpp.git`](https://github.com/weathership/oss-minifi-cpp)
(Apache NiFi MiNiFi C++).

## Role

**Sentinel substrate** for signals-protocol process coordination:

- Thin agents that represent host gRPC engines / agents to a control plane  
- **C2** (command and control) for discrete inventory and reconfiguration  
- **Metrics / OTel** for activity truth and scale-to-zero of **claims**  
- Overwatch-oriented ops surface (with NiFi/MiNiFi C2 UIs)

Host engines remain the execution plane. **YuniKorn** (see
`components/yunikorn-core`) is an optional **admission instance** for sentinel
apps on system-wide RKE2—not the definition of the approach.

Binding design:

`components/signals-protocol/specification/operations/minifi_sentinels.md`

## Related

- [signals-protocol](./signals-protocol.md)  
- [Kerberos](../operations/kerberos.md) / [Secrets](../operations/secrets.md)  
- Upstream: [C2.md](https://github.com/weathership/oss-minifi-cpp/blob/main/C2.md), [METRICS.md](https://github.com/weathership/oss-minifi-cpp/blob/main/METRICS.md)  
