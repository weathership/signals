"""Tests for GPU preflight detection."""

from __future__ import annotations

from sigint.config import GpuInfo, preflight_gpu


def test_preflight_gpu_returns_gpu_info():
    """preflight_gpu() returns a GpuInfo dataclass."""
    gpu = preflight_gpu()
    assert isinstance(gpu, GpuInfo)
    assert gpu.resolved_device in ("cuda", "cpu")


def test_gpu_info_summary_no_gpu():
    """GpuInfo summary when no GPUs are present."""
    gpu = GpuInfo(available=False, device_count=0)
    assert "No NVIDIA GPUs detected" in gpu.summary()


def test_gpu_info_summary_mismatch():
    """GpuInfo summary when driver/PyTorch CUDA versions mismatch."""
    gpu = GpuInfo(
        available=False,
        device_count=6,
        driver_cuda_version="12.4",
        pytorch_cuda_version="12.8",
    )
    assert "CUDA unavailable" in gpu.summary()
    assert "12.4" in gpu.summary()
    assert "12.8" in gpu.summary()


def test_gpu_info_summary_available():
    """GpuInfo summary when GPUs are usable."""
    gpu = GpuInfo(
        available=True,
        device_count=6,
        driver_cuda_version="12.8",
        devices=["RTX 4090 24564 MiB"] * 6,
    )
    assert "6x GPU available" in gpu.summary()
    assert "CUDA 12.8" in gpu.summary()


def test_gpu_info_resolved_device():
    """resolved_device property returns correct string."""
    assert GpuInfo(available=True).resolved_device == "cuda"
    assert GpuInfo(available=False).resolved_device == "cpu"


def test_preflight_gpu_detects_hardware():
    """On this machine with 6x 4090, preflight should detect 6 GPUs."""
    gpu = preflight_gpu()
    # The GPUs are physically present even if CUDA runtime is incompatible
    if gpu.device_count > 0:
        assert gpu.driver_version != ""
        assert gpu.driver_cuda_version != ""
        assert len(gpu.devices) == gpu.device_count
