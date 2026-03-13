# Impala Build Fixes — Nix/Toolchain Compatibility

## Summary

Resolved multiple compatibility issues between the Impala toolchain (built on Ubuntu 22.04)
and the Nix devenv environment to get the full Impala build (`buildall.sh -notests -noclean`)
past the Python virtualenv bootstrap stage.

## Issues Fixed

### 1. OpenSSL Version Conflict (LD_LIBRARY_PATH ordering)

**Problem:** The toolchain Python 3.11's `_ssl.so` was compiled against OpenSSL 3.0.2 (system).
The Nix devenv profile has OpenSSL 3.6.1 at `.devenv/profile/lib/libssl.so.3`, which appears
BEFORE the toolchain GCC lib64 dir in LD_LIBRARY_PATH. The Nix OpenSSL is linked against
Nix glibc 2.42, but the toolchain Python uses system glibc 2.35 — incompatible.

**Fix:** In `bootstrap_virtualenv.py:exec_pip_install()`, prepend the toolchain GCC lib64 dir
to LD_LIBRARY_PATH so the dynamic linker finds the system-compatible OpenSSL first:

```python
gcc_lib64_dir = os.path.join(toolchain_gcc_dir, "lib64")
parts = [p for p in ld_library_path.split(":") if p != gcc_lib64_dir]
env["LD_LIBRARY_PATH"] = ":".join([gcc_lib64_dir] + parts)
```

The SSL symlinks (`libssl.so.3 -> /lib/x86_64-linux-gnu/libssl.so.3`) were already created
in `impala-python3-common.sh` during a previous session.

### 2. Setuptools 80.10.2 `develop` Command Deprecation

**Problem:** `pip install -e lib/python` triggers setuptools 80.x's deprecated `develop`
command, which internally spawns `pip install -e . --use-pep517 --no-deps`. This nested pip
creates an isolated build environment and tries to download setuptools from PyPI, failing
because SSL was unavailable.

**Fix:** Replaced `-e` (editable install) with `--no-deps --no-build-isolation` (non-editable).
This avoids the `develop` command entirely and uses the venv's existing setuptools to build
the wheel:

```python
local_package_install_cmd = impala_pip_base_cmd + \
    ['--no-deps', '--no-build-isolation',
     os.path.join(os.getenv('IMPALA_HOME'), 'lib', 'python')]
```

### 3. SASL Header Missing for Toolchain GCC

**Problem:** The `sasl` Python package needs `sasl/sasl.h` from cyrus-sasl-dev. The Nix devenv
has this at `.devenv/profile/include/sasl/sasl.h`, but the toolchain GCC doesn't search Nix
include paths.

**Fix:** Set `CPATH` and `LIBRARY_PATH` GCC environment variables (not CFLAGS/LDFLAGS which
may not propagate through PEP 517 build isolation):

```python
env["CPATH"] = devenv_include + ":" + existing_cpath
env["LIBRARY_PATH"] = devenv_lib + ":" + existing_library_path
```

### 4. KUDU_BUILD Env Var Conflict

**Problem:** `devenv.nix` exports `KUDU_BUILD=$HOME/local/src/asf/kudu/build/latest`. The
`install_kudu_client_if_possible` function in `bootstrap_virtualenv.py` creates a fake
KUDU_HOME dir with copied headers, but kudu-python's setup.py uses `KUDU_BUILD` from env
(overriding the fake dir's default path). The real build dir doesn't have `src/kudu/util/int128.h`.

**Fix:** Override `KUDU_BUILD` in the env passed to pip:

```python
env["KUDU_BUILD"] = os.path.join(fake_kudu_build_dir, "build", "latest")
```

## Files Modified

| File | Changes |
|------|---------|
| `infra/python/bootstrap_virtualenv.py` | LD_LIBRARY_PATH prepend, --no-build-isolation for lib/python, CPATH/LIBRARY_PATH for devenv headers, KUDU_BUILD override |
| `infra/python/deps/setuptools-80.10.2.tar.gz` | Re-downloaded (was removed during version downgrade attempt) |
| `infra/python/deps/setuptools-69.5.1.tar.gz` | Downloaded (kept for reference, not used) |

## Key Insight

The root cause of ALL SSL-related failures was LD_LIBRARY_PATH ordering. The Nix devenv
profile's `libssl.so.3` (OpenSSL 3.6.1, linked to Nix glibc 2.42) was found before the
system `libssl.so.3` (OpenSSL 3.0.2, linked to system glibc 2.35). Since the toolchain
Python was built against system OpenSSL, it needs the system version.
