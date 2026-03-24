# P2P Driver Upgrade Research: 550.90.07 -> 570.x+

**Date:** 2026-03-23
**Context:** 6x RTX 4090, currently driver 550.90.07 with tinygrad P2P patch.
Need CUDA 12.8 for PyTorch 2.10.0 and CatBoost 1.2.10.

## Summary

Upgrading from 550.90.07-p2p to 570.x-p2p is **safe for RTX 4090** with the tinygrad
P2P patch. Multiple 570.x P2P branches exist and are confirmed working for 4090.
RTX 5090 (Blackwell) has additional issues not relevant to our 4090 setup.

## tinygrad/open-gpu-kernel-modules: 570.x P2P Branches

Three 570.x P2P branches exist in the tinygrad repo:

| Branch | Tag | Head Date |
|--------|-----|-----------|
| `570.124.06-p2p` | `570.124.06-p2p` (not tagged) | 2025-05-05 |
| `570.133.20-p2p` | `570.133.20-p2p` | 2025-05-06 |
| `570.148.08-p2p` | `570.148.08-p2p` | 2025-06-05 |

**Recommended:** `570.148.08-p2p` -- most recent, matches NVIDIA data center release.

### Installation Process (unchanged from 550.x)

```bash
# 1. Install official NVIDIA driver 570.148.08
#    https://docs.nvidia.com/datacenter/tesla/tesla-release-notes-570-148-08/
sudo ./NVIDIA-Linux-x86_64-570.148.08.run --no-kernel-modules

# 2. Build and install P2P-patched kernel modules
git clone https://github.com/tinygrad/open-gpu-kernel-modules.git
cd open-gpu-kernel-modules
git checkout 570.148.08-p2p
./install.sh   # rmmod, make, make install, depmod, nvidia-smi

# 3. Reboot
sudo reboot
```

## aikitoria/open-gpu-kernel-modules: Extended Fork

A more actively maintained fork with broader driver coverage:

| Branch | Notes |
|--------|-------|
| `570.86.16-p2p` | |
| `570.124.04-p2p` | |
| `570.124.06-p2p` | |
| `570.133.07-p2p` | |
| `570.153.02-p2p` | Newer than tinygrad's latest 570.x |
| `575.51.02-p2p` | |
| `575.64.05-p2p` | |
| `580.76.05-p2p` | |
| `580.82.09-p2p` | |
| `580.95.05-p2p` | |
| `580.105.08-p2p` | |
| `590.44.01-p2p` | |
| `590.48.01-p2p` | |
| `595.45.04-p2p` | Latest as of 2026-03 |

The aikitoria fork also includes 5090 P2P fixes (confirmed working by issue #44
reporter). This fork provides a path to 580+ and 590+ drivers in the future.

## NVIDIA Official Repo (NVIDIA/open-gpu-kernel-modules)

**P2P is NOT natively enabled for GeForce in any official driver version.**

NVIDIA has branches `570` and `570.148` in their repo, but these do **not** include
P2P support for GeForce cards. The official position from NVIDIA Engineering is that
"Peer to Peer is not supported on the GeForce RTX 4090" -- P2P is reserved for
professional/data center GPUs (A100, H100, etc.).

The P2P patch works by rewriting `GMMU_APERTURE_PEER` to `GMMU_APERTURE_SYS_NONCOH`,
enabling direct PCIe-based P2P transfers. This is using PCIe according to spec --
the hardware supports it, NVIDIA just disabled it in the driver.

## Known Issues and Prerequisites

### Required BIOS Settings
- **Resizable BAR:** MUST be enabled (BAR1 should show 24GB for 4090)
- **IOMMU:** MUST be disabled (`intel_iommu=off iommu=off` in GRUB)
- **PCIe ACS:** Should be disabled if behind a PCIe switch
- **VT-d:** Disable if experiencing NaN verification errors

### RTX 4090-Specific Status
- **simpleP2P:** PASS (confirmed by multiple users with 570.x branches)
- **p2pBandwidthLatencyTest:** PASS for 4090
- **NCCL all_reduce_perf:** Works, but can hang if PCIe ACS is enabled (issue #45, fixed by disabling ACS)
- **Issue #33:** GPUs behind PCIe switches may show "CANNOT Access Peer" -- Resizable BAR must be enabled

### RTX 5090-Specific Issues (NOT relevant to our setup)
- P2P patch from tinygrad does NOT work for RTX 5090 (Blackwell architecture)
- The aikitoria fork has additional fixes for 5090 (different aperture handling)
- Issue #44: 5090 gets `cudaErrorMapBufferObjectFailed` with tinygrad patches
- Issue #44 confirms aikitoria fork resolves 5090 P2P

## Recommendation

**Proceed with upgrade to driver 570.148.08 using the `570.148.08-p2p` branch from
tinygrad/open-gpu-kernel-modules.** This is the direct successor to our current
550.90.07-p2p setup.

If a newer 570.x point release is needed, the aikitoria fork provides `570.153.02-p2p`.

### Upgrade Checklist

1. [ ] Verify BIOS: Resizable BAR on, IOMMU off, VT-d off
2. [ ] Download NVIDIA-Linux-x86_64-570.148.08.run
3. [ ] Clone tinygrad/open-gpu-kernel-modules, checkout `570.148.08-p2p`
4. [ ] Stop all GPU workloads
5. [ ] Install driver with `--no-kernel-modules`
6. [ ] Run `./install.sh` from patched repo
7. [ ] Reboot
8. [ ] Validate: `nvidia-smi` shows 570.148.08, CUDA 12.8
9. [ ] Validate: `simpleP2P` passes
10. [ ] Validate: `p2pBandwidthLatencyTest` passes
11. [ ] Validate: CatBoost GPU training works
12. [ ] Validate: PyTorch CUDA operations work
