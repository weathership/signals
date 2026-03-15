# devenv Testing Capabilities Research

## Summary

devenv (v1.11.2) has a simple but effective testing framework centered on the
`enterTest` shell hook, with automatic process lifecycle management. It is NOT a
structured test framework with named test blocks or test dependencies. Instead,
it provides a bash script execution environment with helper functions and
automatic service orchestration.

---

## 1. What does `devenv test` do?

The `devenv test` command executes a 6-phase pipeline (from `devenv/src/devenv.rs`):

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Configuring shell | Assembles the Nix environment with `is_testing=true`, builds packages, captures env vars |
| 2 | Running enterShell tasks | Runs setup tasks (venvs, pip install, etc.) -- only if no processes defined |
| 3 | Building tests | Nix-builds `devenv.config.test` into a shell script (GC-rooted at `.devenv/gc/test`) |
| 4 | Starting processes | If processes exist: calls `self.up()` in **detached mode** (equivalent to `devenv up -d`) |
| 5 | Running tests | Executes the built test script via `run_in_shell()` |
| 6 | Stopping processes | If processes were started: calls `self.down()` |

Key behaviors:
- Exit code determines pass/fail -- non-zero = "Tests failed :("
- `devenv test` is aliased as `devenv ci`
- Uses `.devenv/test-state/` as an isolated state directory (separate from shell state)
- The `--override-dotfile` flag creates a fully temporary `.devenv` dir for complete isolation

## 2. What is `enterTest` and how is it used?

`enterTest` is a Nix option of type `lib.types.lines` (from `src/modules/tests.nix`):

```nix
enterTest = lib.mkOption {
  type = lib.types.lines;
  description = "Bash code to execute to run the test.";
};
```

The final test script is assembled from three layers using `lib.mkMerge`:

1. **`lib.mkBefore` (prepended)** -- devenv injects helper functions:
   - `wait_for_port <port> [timeout]` -- polls localhost:port with netcat
   - `wait_for_processes [timeout]` -- waits for all process-compose processes
     to reach Ready state (filters by readiness probes)
   - Both functions are `export -f`'d so they're available in subshells

2. **User's `enterTest`** -- the block defined in `devenv.nix`

3. **`lib.mkAfter` (appended)** -- devenv checks for `.test.sh`:
   ```bash
   if [ -f ./.test.sh ]; then
     echo "Running .test.sh..."
     ./.test.sh
   fi
   ```

The assembled script is wrapped with `set -euo pipefail` and written via
`pkgs.writeShellScript "devenv-test"`.

### Current project enterTest

```nix
enterTest = ''
  echo "Running tests"
  git --version | grep --color=auto "${pkgs.git.version}"
'';
```

This is a minimal smoke test verifying the Nix-provided git is available.

## 3. Can tests run against live services?

**Yes, automatically.** This is a core feature.

When `devenv test` detects processes defined in the config, it:
1. Starts all processes in detached mode (Phase 4)
2. Runs the test script (Phase 5) -- which can use `wait_for_processes` or
   `wait_for_port` to wait for readiness
3. Stops all processes after tests complete (Phase 6)

The process lifecycle is fully managed. The `wait_for_processes` helper
understands process-compose readiness probes and correctly filters processes
that have them vs. those that don't.

**However, `devenv test` does NOT connect to an already-running `devenv up`.**
It starts its own isolated process set using a separate state directory
(`.devenv/test-state/`). This means:
- You cannot run `devenv up` in one terminal and `devenv test` in another
  against the same services (port conflicts)
- Each `devenv test` invocation is self-contained

### Workaround for testing against a running `devenv up`

You can conditionally exclude processes during testing:

```nix
processes = {
  # ... your processes ...
} // lib.optionalAttrs (!config.devenv.isTesting) {
  heavy-service = { ... };  # excluded during testing
};
```

Or exclude ALL processes during testing to run against external services:

```nix
# In enterTest, just test against already-running services
enterTest = ''
  wait_for_port 5455 30  # wait for PG (already running via devenv up)
  uv run pytest tests/
'';
```

Then use `config.devenv.isTesting` to suppress process definitions so
`devenv test` doesn't try to start its own.

## 4. Can devenv integrate with external test frameworks?

**Yes, but only as subprocess calls from enterTest.** There is no structured
integration. External frameworks are invoked as shell commands:

```nix
enterTest = ''
  wait_for_processes 120

  # Python pytest
  uv run pytest tests/ -v

  # Python behave (BDD)
  uv run behave features/ --tags=@tier0

  # Rust
  cargo test

  # Java
  mvn test -pl fe -Dtest="ConfigLoaderTest"

  # Any shell command
  ./scripts/integration-test.sh
'';
```

The `set -euo pipefail` wrapper means the first failing command aborts the
entire test run. For more nuanced control, wrap commands or use `|| true`.

### .test.sh convention

If a `.test.sh` file exists in the project root, it is automatically executed
AFTER the enterTest script. This allows keeping test logic out of `devenv.nix`.

## 5. Test-specific features

### Available features

| Feature | Description |
|---------|-------------|
| `enterTest` | Shell hook for test commands |
| `config.devenv.isTesting` | Boolean, `true` during `devenv test`, `false` otherwise |
| `wait_for_port` | Built-in helper function |
| `wait_for_processes` | Built-in helper function (process-compose aware) |
| `.test.sh` | Auto-executed script file |
| `--override-dotfile` | Full isolation via temp directory |
| `.devenv/test-state/` | Stable test state directory (separate from shell state) |

### Features that DO NOT exist

- `services.test` -- no test-specific service configuration
- `processes.test` -- no test-specific process configuration
- Named test blocks -- no way to define multiple named tests
- Test dependencies -- no DAG of tests
- Test fixtures -- no setup/teardown hooks beyond enterTest itself
- Test filtering -- no way to run a subset of tests (use shell logic)
- Test reporting -- only pass/fail based on exit code
- Parallel test execution -- tests run sequentially in one script

### config.devenv.isTesting

This boolean is the primary mechanism for test-aware configuration:

```nix
# Exclude expensive processes during testing
processes = lib.mkIf (!config.devenv.isTesting) {
  atlas = { ... };
};

# Add test-only packages
packages = lib.optionals config.devenv.isTesting [
  pkgs.postgresql  # psql client for test assertions
];

# Different env vars for testing
env = lib.optionalAttrs config.devenv.isTesting {
  TEST_MODE = "true";
  DATABASE_URL = "postgresql://localhost:5455/signals_test";
};
```

## 6. Relationship between `devenv test` and `devenv up`

| Aspect | `devenv up` | `devenv test` |
|--------|-------------|---------------|
| Purpose | Run services for development | Run tests with optional services |
| State directory | `.devenv/state/` | `.devenv/test-state/` |
| Process lifecycle | Manual (Ctrl-C to stop) | Automatic (start before, stop after) |
| isTesting | `false` | `true` |
| Nix evaluation | Normal | `devenv_istesting = true` |
| enterShell | Runs | Runs (Phase 2) |
| enterTest | Not run | Runs (Phase 5) |
| Port allocation | Uses configured ports | Same ports (potential conflicts!) |

**They are independent invocations.** Running `devenv test` while `devenv up`
is active will cause port conflicts because both try to bind the same ports.

### Strategies for coexistence

1. **Stop `devenv up` before running `devenv test`**
2. **Use `isTesting` to skip processes** and test against the running `devenv up`:
   ```nix
   processes = lib.mkIf (!config.devenv.isTesting) { ... };
   ```
3. **Use different ports during testing** (complex, not recommended)

---

## Recommendations for signals-360

Given the project's test infrastructure (behave BDD features/, pytest, JUnit),
a practical `enterTest` could look like:

```nix
enterTest = ''
  echo "=== signals-360 test suite ==="

  # Option A: Start services via devenv (automatic) and run tests
  wait_for_processes 120

  # Tier 0: Unit tests (no services needed)
  uv run pytest tests/ -v --timeout=60

  # Tier 1: BDD smoke tests
  uv run behave features/ --tags=@tier0 --no-capture

  # Tier 2: Impala FE unit tests (Java)
  cd components/impala
  source bin/impala-config.sh
  mvn test -pl fe \
    -Dtest="ConfigLoaderTest,KuduMetaProviderTest,SignalsDdlExecutorTest" \
    -DfailIfNoTests=false --no-transfer-progress
'';
```

Alternatively, for testing against a running `devenv up` (avoids starting heavy
services like Impala/Kudu during test):

```nix
# Skip all processes during testing -- assume devenv up is running
processes = lib.mkIf (!config.devenv.isTesting) {
  # ... all process definitions ...
};

enterTest = ''
  echo "=== signals-360 test suite (against live services) ==="
  wait_for_port 5455 30    # PostgreSQL
  wait_for_port 21050 30   # Impala

  uv run pytest tests/ -v
  uv run behave features/ --tags=@tier0
'';
```
