# devenv 1.11.x process-compose Configuration Syntax

## Overview

In devenv 1.11.x (the version used in this project), the process manager is
process-compose (the default). Each process defined via `processes.<name>` gets
a `process-compose` attribute that accepts arbitrary process-compose YAML
attributes as a freeform Nix attrset.

The key attribute path is:

```
processes.<name>.process-compose.<any-process-compose-yaml-key>
```

This is typed as `(pkgs.formats.yaml {}).type` — meaning any valid
process-compose YAML structure can be expressed as Nix attrsets.

---

## 1. Readiness Probes

### Exec probe

```nix
processes.my-service = {
  exec = "start-my-service";
  process-compose = {
    readiness_probe = {
      exec.command = "curl -f http://localhost:8080/health";
      initial_delay_seconds = 2;
      period_seconds = 10;
      timeout_seconds = 4;
      success_threshold = 1;
      failure_threshold = 5;
    };
  };
};
```

### HTTP GET probe

```nix
processes.my-api = {
  exec = "start-api";
  process-compose = {
    readiness_probe = {
      http_get = {
        host = "127.0.0.1";
        scheme = "http";
        path = "/health";
        port = 8080;
      };
      initial_delay_seconds = 5;
      period_seconds = 10;
      timeout_seconds = 5;
      success_threshold = 1;
      failure_threshold = 3;
    };
  };
};
```

### Real examples from devenv source

PostgreSQL (exec probe):
```nix
processes.postgres.process-compose = {
  readiness_probe = {
    exec.command = ''pg_isready -d template1 && psql -c "SELECT 1" template1'';
    initial_delay_seconds = 2;
    period_seconds = 10;
    timeout_seconds = 4;
    success_threshold = 1;
    failure_threshold = 5;
  };
  availability.restart = "on_failure";
};
```

Kafka Connect (HTTP probe + depends_on):
```nix
processes.kafka-connect.process-compose = {
  readiness_probe = {
    initial_delay_seconds = 2;
    http_get = {
      path = "/connectors";
      port = 8083;
    };
  };
  depends_on.kafka.condition = "process_healthy";
};
```

---

## 2. Process Dependencies (depends_on)

```nix
processes.my-app = {
  exec = "start-app";
  process-compose = {
    depends_on = {
      postgres = {
        condition = "process_healthy";  # requires readiness_probe on postgres
      };
      migrations = {
        condition = "process_completed_successfully";  # one-shot dependency
      };
    };
  };
};
```

### Available conditions

| Condition                        | Meaning                                    |
|----------------------------------|--------------------------------------------|
| `process_started`                | Default; fires as soon as process launches |
| `process_completed`              | Fires when process exits (any exit code)   |
| `process_completed_successfully` | Fires when process exits with code 0       |
| `process_healthy`                | Fires when readiness_probe passes          |
| `process_log_ready`              | Fires when ready_log_line matches in logs  |

---

## 3. One-Shot Process (runs once and exits)

### Fire-and-forget (no restart)

```nix
processes.run-migrations = {
  exec = "dbmate up";
  process-compose = {
    availability = {
      restart = "no";       # do not restart after exit
    };
    depends_on = {
      postgres = {
        condition = "process_healthy";
      };
    };
  };
};
```

### One-shot that shuts down everything on completion

```nix
processes.integration-tests = {
  exec = "pytest tests/";
  process-compose = {
    availability = {
      restart = "no";
      exit_on_end = true;   # shut down all processes when this one exits
    };
    depends_on = {
      my-app = {
        condition = "process_healthy";
      };
    };
  };
};
```

---

## 4. Top-Level process-compose Settings

For global/top-level process-compose.yaml options (not per-process), use:

```nix
process.managers.process-compose.settings = {
  # any top-level process-compose.yaml keys
  version = "0.5";
  log_location = "/tmp/pc.log";
};
```

---

## 5. Other Useful Per-Process Attributes

```nix
processes.worker.process-compose = {
  # Restart policy
  availability = {
    restart = "on_failure";   # "no", "always", "on_failure", "exit_on_failure"
    backoff_seconds = 2;
    max_restarts = 5;         # 0 = unlimited
  };

  # Shutdown signal
  shutdown.signal = 2;  # SIGINT

  # Environment (process-specific)
  environment = [ "MY_VAR=value" ];

  # Namespace / grouping (process-compose TUI)
  namespace = "backend";
};
```

---

## Important Notes for devenv 1.11.x

- `process.manager.implementation` defaults to `"process-compose"` in 1.11.x
- The `process-compose` attribute on each process is a **freeform YAML type** --
  there is no Nix-level type checking of sub-attributes; any valid
  process-compose YAML key works
- devenv 2.0 (March 2026) replaces process-compose with a native Rust manager
  and introduces different syntax (`ready`, `after`, `restart`). The 1.11.x
  syntax documented here uses the process-compose YAML attribute names directly.
- To use process-compose in devenv 2.0, set
  `process.manager.implementation = "process-compose";`
