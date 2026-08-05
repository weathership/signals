{ pkgs, lib, config, inputs, ... }:

let
  # Shared LD_LIBRARY_PATH setup for all Impala processes.
  # Nix glibc must come FIRST so libc.so.6 resolves to glibc 2.42.
  # This binding is only forced on Linux (impala processes are gated by mkIf below);
  # on Darwin pkgs.glibc is never evaluated, so the ${pkgs.glibc} reference is safe.
  impalaLdLibraryPath = ''
    NIX_GLIBC="${pkgs.glibc}/lib"
    GCC_LIB64="$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/lib64"
    NIX_KRB5="${pkgs.krb5.lib}/lib"
    export LD_LIBRARY_PATH="$NIX_GLIBC:$GCC_LIB64:$NIX_KRB5:$LD_LIBRARY_PATH:/lib/x86_64-linux-gnu"
  '';

  # JVM flags for HMS-free catalog mode
  hmsFreeJavaOpts = builtins.concatStringsSep " " [
    "-Dsignals.hms_free_mode=true"
    "-Dsignals.catalog.jdbc_url=jdbc:postgresql://localhost:5455/signals_catalog"
    "-Dsignals.kudu.master_addresses=127.0.0.1:7051"
  ];
in
{
  dotenv.enable = true;

  # ── Packages ───────────────────────────────────────────────────────────────
  packages = with pkgs; [
    # Core
    git
    gh
    jq
    just

    # Kerberos / Security
    krb5
    cyrus_sasl
    openssl

    # ASF build dependencies (Kudu, Impala)
    cmake
    ninja
    gcc
    protobuf
    flatbuffers
    zlib  # needed by numpy C extensions in pip wheels

    # Kubernetes / Orchestration
    kubectl
    kubernetes-helm
    tilt
    k9s
    k3d
    podman

    # Infrastructure / Deployment
    awscli2
    opentofu
    ansible
    zarf
    conftest
    cloudflared

    # gRPC
    grpcurl

    # WASM (Ghostty terminal component)
    wasmtime
    wasm-pack
    wasm-bindgen-cli
    binaryen

    # Database
    dbmate
    # impala_fdw HS2 thrift client
    thrift
    boost
    boost.dev
    # Documentation
    mdbook
    mdbook-d2
    mdbook-katex
    mdbook-mermaid
    d2
    graphviz

    # Utilities
    presenterm
    imagemagick
    wget
  ];

  # ── Languages ──────────────────────────────────────────────────────────────
  languages.rust.enable = true;

  languages.python = {
    enable = true;
    package = pkgs.python312;
    uv.enable = true;
  };

  languages.java = {
    enable = true;
    jdk.package = pkgs.jdk21;
    maven.enable = true;
  };

  languages.javascript = { enable = true; };
  languages.typescript = { enable = true; };

  # ── Environment ────────────────────────────────────────────────────────────
  # Kerberos: realm includes env segment — DEV.VISTA.ZNDX.ORG
  # ({ENV}.{LOCATION}.ZNDX.ORG). Host FQDN tinybox.dev.vista.zndx.org.
  # User principal signals@DEV.VISTA.ZNDX.ORG → PG role "signals".
  # KDC stays on loopback :8848.
  env = {
    KRB5_REALM = "DEV.VISTA.ZNDX.ORG";
    KRB5_KDC_PORT = "8848";
    SIGNALS_KRB_ENV = "dev";
    SIGNALS_KRB_LOCATION = "vista";
    SIGNALS_KRB_HOST = "tinybox.dev.vista.zndx.org";
  };

  # ── PostgreSQL ─────────────────────────────────────────────────────────────
  services.postgres = {
    enable = true;
    package = pkgs.postgresql_16;
    extensions = extensions: [
      extensions.age
      extensions.pg_cron
    ];
    port = 5455;
    settings = {
      listen_addresses = lib.mkForce "127.0.0.1";
      shared_preload_libraries = "age,pg_cron";
      "cron.database_name" = "signals";
    };
    initialDatabases = [
      {
        name = "signals";
        initialSQL = ''
          CREATE EXTENSION IF NOT EXISTS age;
          LOAD 'age';
          SET search_path = ag_catalog, "$user", public;
          CREATE EXTENSION IF NOT EXISTS pg_cron;
          CREATE EXTENSION IF NOT EXISTS pg_trgm;
        '';
      }
      { name = "polaris"; }
      { name = "signals_catalog"; }
      { name = "ranger"; }
    ];
  };

  # ── KDC Process ────────────────────────────────────────────────────────────
  processes.kdc = {
    exec = ''
      # Initialize KDC if needed
      bash scripts/kdc-init.sh

      KDC_DIR="$PWD/.devenv/kdc"

      echo "Starting KDC on 127.0.0.1:''${KRB5_KDC_PORT:-8848}..."
      exec env \
        KRB5_CONFIG="$KDC_DIR/krb5.conf" \
        KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
        krb5kdc -n
    '';
    process-compose = {
      readiness_probe = {
        exec.command = "ss -uln | grep -q 8848";
        initial_delay_seconds = 1;
        period_seconds = 5;
        timeout_seconds = 2;
        success_threshold = 1;
        failure_threshold = 10;
      };
    };
  };

  # ── Atlas Process (AGE backend on signals PG; HTTP :21010 to coexist with aegir :21000) ──
  processes.atlas = {
    exec = ''
      ATLAS_DIR="$PWD/components/atlas"
      ATLAS_WEBAPP="$ATLAS_DIR/webapp/target/atlas-webapp-3.0.0-SNAPSHOT"
      ATLAS_CONF_SRC="$PWD/config/atlas"
      ATLAS_HOME="$PWD/.devenv/atlas"
      PGPORT="''${PGPORT:-5455}"

      mkdir -p "$ATLAS_HOME/data" "$ATLAS_HOME/logs" "$ATLAS_HOME/conf"

      # Symlink models so AtlasTypeDefStoreInitializer finds bootstrap type definitions
      ln -sfn "$ATLAS_DIR/addons/models" "$ATLAS_HOME/models"

      # Materialize conf with live PG port (Atlas does not interpolate env reliably)
      sed "s|localhost:[0-9]*/signals|localhost:$PGPORT/signals|" \
        "$ATLAS_CONF_SRC/atlas-application.properties" > "$ATLAS_HOME/conf/atlas-application.properties"
      cp -f "$ATLAS_CONF_SRC/users-credentials.properties" "$ATLAS_HOME/conf/" 2>/dev/null || true
      cp -f "$ATLAS_CONF_SRC/atlas-simple-authz-policy.json" "$ATLAS_HOME/conf/" 2>/dev/null || true

      if [ ! -d "$ATLAS_WEBAPP/WEB-INF" ]; then
        echo "Atlas webapp not built. Run: devenv tasks run atlas:build"
        exit 1
      fi

      # Hikari fail-fasts without retry — wait for Postgres
      for _i in $(seq 1 90); do
        pg_isready -h localhost -p "$PGPORT" -q && break
        sleep 1
      done

      echo "Starting Atlas on http://localhost:21010 (AGE -> signals DB, pg :$PGPORT)..."
      exec java \
        -Datlas.home="$ATLAS_HOME" \
        -Datlas.conf="$ATLAS_HOME/conf" \
        -Datlas.log.dir="$ATLAS_HOME/logs" \
        -Datlas.log.file=application \
        -Datlas.data="$ATLAS_HOME/data" \
        -Dlogback.configurationFile="$ATLAS_DIR/distro/src/conf/atlas-logback.xml" \
        -Datlas.graphdb.backend=org.apache.atlas.repository.graphdb.age.AtlasAgeGraphDatabase \
        -Djava.net.preferIPv4Stack=true \
        --add-opens java.base/java.lang=ALL-UNNAMED \
        --add-opens java.base/java.lang.reflect=ALL-UNNAMED \
        --add-opens java.base/java.io=ALL-UNNAMED \
        --add-opens java.base/java.net=ALL-UNNAMED \
        --add-opens java.base/java.util=ALL-UNNAMED \
        --add-opens java.base/java.util.concurrent=ALL-UNNAMED \
        --add-opens java.base/sun.nio.ch=ALL-UNNAMED \
        --add-opens java.base/sun.security.action=ALL-UNNAMED \
        --add-opens java.security.jgss/sun.security.krb5=ALL-UNNAMED \
        -server -Xmx1024m \
        -cp "$ATLAS_HOME/conf:$ATLAS_WEBAPP/WEB-INF/classes:$ATLAS_WEBAPP/WEB-INF/lib/*" \
        org.apache.atlas.Atlas \
        -app "$ATLAS_WEBAPP" \
        -port 21010
    '';
    process-compose = {
      depends_on = {
        postgres = { condition = "process_healthy"; };
      };
      readiness_probe = {
        exec.command = "curl -sf http://127.0.0.1:21010/api/atlas/admin/status";
        initial_delay_seconds = 10;
        period_seconds = 10;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 15;
      };
    };
  };

  # ── Kudu Master Process ──────────────────────────────────────────────────
  processes.kudu-master = {
    exec = ''
      KUDU_HOME="$PWD/.devenv/kudu"
      # Prefer submodule build; allow KUDU_BUILD override for emergency external trees
      KUDU_BUILD="''${KUDU_BUILD:-$PWD/components/kudu/build/latest}"

      if [ ! -f "$KUDU_BUILD/bin/kudu-master" ]; then
        echo "Kudu not built. Run: devenv tasks run kudu:build-cpp"
        exit 1
      fi

      mkdir -p "$KUDU_HOME/master/data" "$KUDU_HOME/master/wal" "$KUDU_HOME/master/logs"

      echo "Starting Kudu Master on localhost:7051..."
      exec "$KUDU_BUILD/bin/kudu-master" \
        --fs_data_dirs="$KUDU_HOME/master/data" \
        --fs_wal_dir="$KUDU_HOME/master/wal" \
        --log_dir="$KUDU_HOME/master/logs" \
        --webserver_port=8051 \
        --rpc_bind_addresses=127.0.0.1:7051 \
        --unlock_unsafe_flags \
        --default_num_replicas=1
    '';
    process-compose = {
      readiness_probe = {
        http_get = {
          host = "127.0.0.1";
          port = 8051;
          path = "/";
        };
        initial_delay_seconds = 2;
        period_seconds = 5;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 10;
      };
    };
  };

  # ── Kudu Tablet Server Process ───────────────────────────────────────────
  processes.kudu-tserver = {
    exec = ''
      KUDU_HOME="$PWD/.devenv/kudu"
      KUDU_BUILD="''${KUDU_BUILD:-$PWD/components/kudu/build/latest}"

      if [ ! -f "$KUDU_BUILD/bin/kudu-tserver" ]; then
        echo "Kudu not built. Run: devenv tasks run kudu:build-cpp"
        exit 1
      fi

      mkdir -p "$KUDU_HOME/tserver/data" "$KUDU_HOME/tserver/wal" "$KUDU_HOME/tserver/logs"

      echo "Starting Kudu Tablet Server..."
      exec "$KUDU_BUILD/bin/kudu-tserver" \
        --fs_data_dirs="$KUDU_HOME/tserver/data" \
        --fs_wal_dir="$KUDU_HOME/tserver/wal" \
        --log_dir="$KUDU_HOME/tserver/logs" \
        --tserver_master_addrs=127.0.0.1:7051 \
        --webserver_port=8050 \
        --rpc_bind_addresses=127.0.0.1:7050 \
        --unlock_unsafe_flags
    '';
    process-compose = {
      depends_on = {
        kudu-master = { condition = "process_healthy"; };
      };
      readiness_probe = {
        http_get = {
          host = "127.0.0.1";
          port = 8050;
          path = "/";
        };
        initial_delay_seconds = 2;
        period_seconds = 5;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 10;
      };
    };
  };

  # ── Impala Runtime Environment ────────────────────────────────────────
  # Impala binaries were built with toolchain GCC 10.4.0 but link against
  # Nix-provided SASL (glibc 2.42) and JVM. We use Nix's ld-linux as the
  # explicit interpreter so that Nix libraries (which need glibc 2.42) work
  # alongside system libraries (which only need glibc ≤2.35, backward-
  # compatible with 2.42). LD_LIBRARY_PATH ordering is critical: Nix glibc
  # must come FIRST so libc.so.6 resolves to glibc 2.42.
  #
  # The three impala-* processes are gated on isLinux: pkgs.glibc is
  # unavailable on Darwin, and Impala itself only runs on Linux x86_64.
  # mkIf with a false condition drops the entire submodule before its
  # contents (including ${pkgs.glibc} interpolations) are forced.

  # ── Impala Statestore Process ───────────────────────────────────────────
  processes.impala-statestore = lib.mkIf pkgs.stdenv.isLinux {
    exec = ''
      IMPALA_HOME="$PWD/components/impala"
      if [ ! -f "$IMPALA_HOME/be/build/latest/service/statestored" ]; then
        echo "Impala not built. Run: devenv tasks run impala:build"; exit 1
      fi
      source "$IMPALA_HOME/bin/impala-config.sh"
      . "$IMPALA_HOME/bin/set-ld-library-path.sh"
      ${impalaLdLibraryPath}

      mkdir -p "$PWD/.devenv/impala/statestore/logs"

      echo "Starting Impala Statestore on port 24000..."
      exec ${pkgs.glibc}/lib/ld-linux-x86-64.so.2 \
        "$IMPALA_HOME/be/build/latest/service/statestored" \
        --state_store_port=24000 \
        --webserver_port=25010 \
        --log_dir="$PWD/.devenv/impala/statestore/logs" \
        --hostname=localhost
    '';
    process-compose = {
      readiness_probe = {
        http_get = {
          host = "127.0.0.1";
          port = 25010;
          path = "/";
        };
        initial_delay_seconds = 3;
        period_seconds = 5;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 10;
      };
    };
  };

  # ── Impala Catalog Server Process (HMS-free) ────────────────────────────
  processes.impala-catalogd = lib.mkIf pkgs.stdenv.isLinux {
    exec = ''
      IMPALA_HOME="$PWD/components/impala"
      if [ ! -f "$IMPALA_HOME/be/build/latest/service/catalogd" ]; then
        echo "Impala not built. Run: devenv tasks run impala:build"; exit 1
      fi
      source "$IMPALA_HOME/bin/impala-config.sh"
      . "$IMPALA_HOME/bin/set-classpath.sh"
      . "$IMPALA_HOME/bin/set-ld-library-path.sh"
      ${impalaLdLibraryPath}

      # Add project config (hive-site.xml, core-site.xml) to classpath
      export CLASSPATH="$PWD/config/impala:$CLASSPATH"

      # Initialize catalog schema (idempotent)
      psql -p 5455 -d signals_catalog -f "$PWD/config/impala/catalog_schema.sql"

      export JAVA_TOOL_OPTIONS="''${JAVA_TOOL_OPTIONS:-} ${hmsFreeJavaOpts}"

      mkdir -p "$PWD/.devenv/impala/catalogd/logs"

      echo "Starting Impala Catalog Server on port 26000 (HMS-free)..."
      exec ${pkgs.glibc}/lib/ld-linux-x86-64.so.2 \
        "$IMPALA_HOME/be/build/latest/service/catalogd" \
        --catalog_service_port=26000 \
        --state_store_subscriber_port=23020 \
        --state_store_host=localhost \
        --state_store_port=24000 \
        --webserver_port=25020 \
        --log_dir="$PWD/.devenv/impala/catalogd/logs" \
        --hostname=localhost \
        --kudu_master_hosts=127.0.0.1:7051 \
        --abort_on_config_error=false \
        --hms_event_polling_interval_s=0
    '';
    process-compose = {
      depends_on = {
        impala-statestore = { condition = "process_healthy"; };
        kudu-tserver = { condition = "process_healthy"; };
        postgres = { condition = "process_healthy"; };
      };
      readiness_probe = {
        http_get = {
          host = "127.0.0.1";
          port = 25020;
          path = "/";
        };
        initial_delay_seconds = 5;
        period_seconds = 5;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 15;
      };
    };
  };

  # ── Impala Daemon Process (HMS-free) ────────────────────────────────────
  processes.impala-impalad = lib.mkIf pkgs.stdenv.isLinux {
    exec = ''
      IMPALA_HOME="$PWD/components/impala"
      if [ ! -f "$IMPALA_HOME/be/build/latest/service/impalad" ]; then
        echo "Impala not built. Run: devenv tasks run impala:build"; exit 1
      fi
      source "$IMPALA_HOME/bin/impala-config.sh"
      . "$IMPALA_HOME/bin/set-classpath.sh"
      . "$IMPALA_HOME/bin/set-ld-library-path.sh"
      ${impalaLdLibraryPath}

      # Add project config (hive-site.xml, core-site.xml) to classpath
      export CLASSPATH="$PWD/config/impala:$CLASSPATH"

      export JAVA_TOOL_OPTIONS="''${JAVA_TOOL_OPTIONS:-} ${hmsFreeJavaOpts}"

      mkdir -p "$PWD/.devenv/impala/impalad/logs"

      echo "Starting Impala Daemon on hs2://localhost:21050..."
      exec ${pkgs.glibc}/lib/ld-linux-x86-64.so.2 \
        "$IMPALA_HOME/be/build/latest/service/impalad" \
        --hs2_port=21050 \
        --beeswax_port=21001 \
        --state_store_subscriber_port=23000 \
        --state_store_host=localhost \
        --state_store_port=24000 \
        --catalog_service_host=localhost \
        --catalog_service_port=26000 \
        --webserver_port=25000 \
        --krpc_port=27000 \
        --log_dir="$PWD/.devenv/impala/impalad/logs" \
        --hostname=localhost \
        --kudu_master_hosts=127.0.0.1:7051 \
        --use_local_catalog=true \
        --abort_on_config_error=false \
        --hms_event_polling_interval_s=0
    '';
    process-compose = {
      depends_on = {
        impala-catalogd = { condition = "process_healthy"; };
      };
      readiness_probe = {
        http_get = {
          host = "127.0.0.1";
          port = 25000;
          path = "/";
        };
        initial_delay_seconds = 5;
        period_seconds = 5;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 15;
      };
    };
  };

  # ── Tasks ──────────────────────────────────────────────────────────────────
  tasks = {
    "signals:kdc-init" = {
      exec = ''
        bash scripts/kdc-init.sh
      '';
      description = "Initialize or verify KDC database and principals";
    };

    "signals:kdc-reset" = {
      exec = ''
        bash scripts/kdc-init.sh --reset
      '';
      description = "Reset KDC database (destroys all principals and keytabs)";
    };

    "sigint:resolve-config" = {
      exec = ''
        uv run python -c "from sigint.config import load_config, materialize_config; materialize_config(load_config(), 'build/config/sigint.env')"
        echo "Resolved config -> build/config/sigint.env"
      '';
      description = "Resolve HOCON config + env vars to build/config/sigint.env";
    };

    "sigint:cache-models" = {
      exec = ''
        mkdir -p build/models
        echo "Downloading sentence-transformers model to build/models/ ..."
        HF_HUB_OFFLINE=0 SENTENCE_TRANSFORMERS_HOME="$PWD/build/models" \
          uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
        echo "Model cached. Pipeline will run offline (HF_HUB_OFFLINE=1)."
      '';
      description = "Pre-download embedding model for air-gap operation";
    };

    "signals:catalog-init" = {
      exec = ''
        psql -p 5455 -d signals_catalog -f config/impala/catalog_schema.sql
      '';
      description = "Initialize the signals catalog registry schema in PostgreSQL";
    };

    "docs:build" = {
      exec = ''
        mdbook build docs/current
      '';
      description = "Build mdbook documentation";
    };

    "docs:serve" = {
      exec = ''
        mdbook serve docs/current --open
      '';
      description = "Serve mdbook documentation with live reload";
    };

    "atlas:build" = {
      exec = ''
        cd components/atlas
        # Create empty apidocs dir so WAR plugin succeeds when enunciate is skipped
        mkdir -p webapp/target/api/v2/apidocs/ui
        mvn package -pl webapp -am -Dmaven.test.skip=true -DskipUTs=true \
          -DGRAPH-PROVIDER=age -Dcheckstyle.skip=true -DskipEnunciate=true \
          --no-transfer-progress
      '';
      description = "Build Atlas webapp with AGE backend";
    };

    "impala-fdw:build" = {
      exec = ''
        if [ ! -f components/impala_fdw/Makefile ]; then
          echo "components/impala_fdw not initialized. Run: git submodule update --init components/impala_fdw"
          exit 1
        fi
        # Thrift + boost from devenv packages (ABI-matched HS2 client)
        export THRIFT_HOME="${pkgs.thrift}"
        export BOOST_HOME="${pkgs.boost.dev}"
        cd components/impala_fdw
        make clean 2>/dev/null || true
        make with_llvm=no \
          THRIFT_HOME="$THRIFT_HOME" \
          BOOST_HOME="$BOOST_HOME" \
          PG_CPPFLAGS="-I$BOOST_HOME/include -I$THRIFT_HOME/include -Isrc -Igen-cpp"
        echo "impala_fdw.so built (HS2 thrift client; NOSASL ready, Kerberos next)."
        echo "Smoke (Impala up): make hs2-smoke && ./tools/hs2_smoke 127.0.0.1 21050"
        echo "Install: make install && psql -p 5455 -d signals -c 'CREATE EXTENSION impala_fdw'"
      '';
      description = "Build PostgreSQL Impala FDW with HS2 thrift client";
    };

    "hms:install" = {
      exec = ''
        HMS_HOME="$PWD/.devenv/hms"
        HMS_VERSION="4.2.0"
        HMS_URL="https://dlcdn.apache.org/hive/hive-standalone-metastore-$HMS_VERSION/hive-standalone-metastore-$HMS_VERSION-bin.tar.gz"

        if [ -d "$HMS_HOME/lib" ]; then
          echo "HMS already installed at $HMS_HOME"
          exit 0
        fi

        echo "Downloading Hive Standalone Metastore $HMS_VERSION..."
        mkdir -p "$HMS_HOME"
        TMP_DIR=$(mktemp -d)
        curl -fSL "$HMS_URL" -o "$TMP_DIR/hms.tar.gz"
        tar -xzf "$TMP_DIR/hms.tar.gz" -C "$TMP_DIR"
        cp -r "$TMP_DIR"/apache-hive-metastore-*/lib "$HMS_HOME/"
        cp -r "$TMP_DIR"/apache-hive-metastore-*/scripts "$HMS_HOME/"
        rm -rf "$TMP_DIR"

        # Add PostgreSQL JDBC driver if not present
        PG_JDBC="postgresql-42.7.4.jar"
        if [ ! -f "$HMS_HOME/lib/$PG_JDBC" ]; then
          echo "Downloading PostgreSQL JDBC driver..."
          curl -fSL "https://jdbc.postgresql.org/download/$PG_JDBC" -o "$HMS_HOME/lib/$PG_JDBC"
        fi

        echo "HMS installed at $HMS_HOME"
      '';
      description = "Download and install Hive Standalone Metastore";
    };

    "hms:init-schema" = {
      exec = ''
        HMS_HOME="$PWD/.devenv/hms"
        HMS_CONF="$PWD/config/hms"

        if [ ! -d "$HMS_HOME/lib" ]; then
          echo "HMS not installed. Run: devenv tasks run hms:install"
          exit 1
        fi

        echo "Initializing HMS schema in PostgreSQL..."
        java \
          --add-opens java.base/java.lang=ALL-UNNAMED \
          --add-opens java.base/java.lang.reflect=ALL-UNNAMED \
          --add-opens java.base/java.net=ALL-UNNAMED \
          --add-opens java.base/java.util=ALL-UNNAMED \
          -cp "$HMS_CONF:$HMS_HOME/lib/*" \
          org.apache.hadoop.hive.metastore.tools.MetastoreSchemaTool \
          -dbType postgres \
          -initSchema \
          --verbose
      '';
      description = "Initialize HMS schema in PostgreSQL (run once)";
    };

    "kudu:install-java" = {
      exec = ''
        if [ ! -d components/kudu/java ]; then
          echo "components/kudu not initialized. Run: git submodule update --init components/kudu"
          exit 1
        fi
        cd components/kudu/java
        ./gradlew :kudu-client:publishToMavenLocal
      '';
      description = "Install Kudu Java client to local Maven repo (from components/kudu)";
    };

    "kudu:build-cpp" = {
      exec = ''
        KUDU_SRC="$PWD/components/kudu"
        if [ ! -d "$KUDU_SRC" ] || [ ! -f "$KUDU_SRC/CMakeLists.txt" ]; then
          echo "components/kudu not initialized. Run: git submodule update --init components/kudu"
          exit 1
        fi
        mkdir -p "$KUDU_SRC/build/release"
        cd "$KUDU_SRC/build/release"
        # Clear cmake cache if OpenSSL version changed
        if [ -f CMakeCache.txt ]; then
          CACHED_SSL=$(grep OPENSSL_SSL_LIBRARY CMakeCache.txt 2>/dev/null | head -1)
          CURRENT_SSL=$(which openssl 2>/dev/null | xargs readlink -f 2>/dev/null || true)
          if echo "$CACHED_SSL" | grep -q "openssl-3.0" && ! echo "$CURRENT_SSL" | grep -q "openssl-3.0"; then
            echo "OpenSSL version changed, clearing cmake cache..."
            rm -f CMakeCache.txt
          fi
        fi
        cmake -DCMAKE_BUILD_TYPE=Release -GNinja -DNO_TESTS=1 ../..
        ninja kudu-master kudu-tserver
        ln -sfn "$KUDU_SRC/build/release" "$KUDU_SRC/build/latest"
        echo "Kudu binaries: $KUDU_SRC/build/latest/bin/"
      '';
      description = "Build Kudu C++ master and tserver from components/kudu";
    };

    "impala:bootstrap" = {
      exec = ''
        cd components/impala
        source bin/impala-config.sh
        python3 bin/bootstrap_toolchain.py
      '';
      description = "Download Impala toolchain (~5-10 GB)";
    };

    "impala:build" = {
      exec = ''
        cd components/impala
        source bin/impala-config.sh
        ./buildall.sh -notests -noclean
      '';
      description = "Full Impala build (C++ backend + Java frontend)";
    };

    "impala:build-fe" = {
      exec = ''
        cd components/impala
        source bin/impala-config.sh
        cd java && mvn compile -pl ../fe -am -DskipTests --no-transfer-progress
      '';
      description = "Incremental Impala frontend build (Java only)";
    };

    "impala:test-fe" = {
      exec = ''
        cd components/impala
        source bin/impala-config.sh
        mvn test -pl fe \
          -Dtest="ConfigLoaderTest,KuduMetaProviderTest,SignalsDdlExecutorTest" \
          -DfailIfNoTests=false --no-transfer-progress
      '';
      description = "Run Impala FE unit tests for signals changes";
    };

    "polaris:install" = {
      exec = ''
        POLARIS_HOME="$PWD/.devenv/polaris"

        if [ -f "$POLARIS_HOME/polaris-quarkus-server.jar" ] || [ -d "$POLARIS_HOME/lib" ]; then
          echo "Polaris already installed at $POLARIS_HOME"
          exit 0
        fi

        echo "Building Apache Polaris from source..."
        POLARIS_SRC="$PWD/.devenv/polaris-src"

        if [ ! -d "$POLARIS_SRC" ]; then
          git clone --depth 1 https://github.com/apache/polaris.git "$POLARIS_SRC"
        fi

        cd "$POLARIS_SRC"
        ./gradlew :polaris-quarkus-server:build -x test -x intTest --no-daemon

        mkdir -p "$POLARIS_HOME"
        cp quarkus/server/build/quarkus-app/quarkus-run.jar "$POLARIS_HOME/polaris-quarkus-server.jar" 2>/dev/null || true
        if [ -d quarkus/server/build/quarkus-app/lib ]; then
          cp -r quarkus/server/build/quarkus-app/lib "$POLARIS_HOME/"
          cp -r quarkus/server/build/quarkus-app/app "$POLARIS_HOME/" 2>/dev/null || true
          cp -r quarkus/server/build/quarkus-app/quarkus "$POLARIS_HOME/" 2>/dev/null || true
        fi

        echo "Polaris installed at $POLARIS_HOME"
      '';
      description = "Build and install Apache Polaris (Iceberg REST catalog)";
    };
  };

  # ── Shell ──────────────────────────────────────────────────────────────────
  enterShell = ''
    KDC_DIR="$PWD/.devenv/kdc"
    export KRB5_CONFIG="$KDC_DIR/krb5.conf"
    export KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf"
    export KRB5CCNAME="$KDC_DIR/krb5cc"

    # Kudu build location (submodule; override with KUDU_BUILD if needed)
    export KUDU_BUILD="''${KUDU_BUILD:-$PWD/components/kudu/build/latest}"

    # Air-gap safe: use local model cache, no HuggingFace phone-home
    export HF_HUB_OFFLINE=1
    export SENTENCE_TRANSFORMERS_HOME="$PWD/build/models"

    # NVIDIA driver libs for PyTorch/CatBoost CUDA.
    # Nix ld-linux doesn't search /lib/x86_64-linux-gnu/ (which also has
    # a conflicting glibc).  Symlink just the driver .so files into a
    # clean directory and prepend it to LD_LIBRARY_PATH.
    NVIDIA_DRIVER_LIBS="$PWD/.devenv/nvidia-driver-libs"
    if [ -e /lib/x86_64-linux-gnu/libcuda.so.1 ]; then
      mkdir -p "$NVIDIA_DRIVER_LIBS"
      for lib in libcuda libnvidia-ml libnvidia-ptxjitcompiler; do
        for f in /lib/x86_64-linux-gnu/''${lib}.so*; do
          [ -e "$f" ] && ln -sfn "$f" "$NVIDIA_DRIVER_LIBS/$(basename "$f")"
        done
      done
      export LD_LIBRARY_PATH="$NVIDIA_DRIVER_LIBS''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    fi

    # OpenTofu alias
    alias tf=tofu

    echo "signals-360 development environment"
    echo ""
    echo "Secrets: secretspec.toml (provider=dotenv via devenv.yaml) — see docs/operations/secrets.md"
    echo "  secretspec run -- <cmd>   # inject declared secrets without shell export"
    echo ""
    echo "Core services (start with 'devenv up'):"
    echo "  PostgreSQL 16     — port 5455, extensions: age, pg_cron"
    echo "  Kerberos KDC      — realm: DEV.VISTA.ZNDX.ORG, host: tinybox.dev.vista.zndx.org, port: 8848"
    echo "  Atlas             — http://localhost:21010 (AGE backend → signals DB)"
    echo "  Ranger Admin      — http://localhost:6080 (when configured)"
    echo "  Kudu Master       — localhost:7051 (web UI: 8051)"
    echo "  Kudu TServer      — localhost:7050 (web UI: 8050)"
    echo "  Impala Statestore — localhost:24000 (web UI: 25010)"
    echo "  Impala Catalogd   — localhost:26000 (web UI: 25020, HMS-free)"
    echo "  Impala Daemon     — hs2://localhost:21050 (web UI: 25000)"
    echo ""
    echo "Connect: jdbc:hive2://localhost:21050/default;auth=noSasl"
    echo ""
    echo "Build tasks:"
    echo "  devenv tasks run kudu:build-cpp       — Build Kudu C++ binaries"
    echo "  devenv tasks run kudu:install-java    — Install Kudu Java client to Maven"
    echo "  devenv tasks run impala:bootstrap     — Download Impala toolchain (~5-10 GB)"
    echo "  devenv tasks run impala:build         — Full Impala build (C++ + Java)"
    echo "  devenv tasks run impala:build-fe      — Incremental Java frontend build"
    echo "  devenv tasks run impala:test-fe       — Run signals FE unit tests"
    echo "  devenv tasks run atlas:build          — Build Atlas webapp (AGE)"
    echo ""
    echo "Utility tasks:"
    echo "  devenv tasks run sigint:resolve-config — Resolve config to build/config/sigint.env"
    echo "  devenv tasks run sigint:cache-models   — Pre-download models for offline use"
    echo "  devenv tasks run signals:kdc-init     — Initialize KDC"
    echo "  devenv tasks run signals:kdc-reset    — Reset KDC database"
    echo "  devenv tasks run signals:catalog-init — Initialize catalog registry schema"
    echo "  devenv tasks run hms:install          — Download Hive Standalone Metastore"
    echo "  devenv tasks run hms:init-schema      — Initialize HMS schema in PostgreSQL"
    echo "  devenv tasks run polaris:install       — Build and install Polaris"
    echo "  devenv tasks run docs:build           — Build documentation"
    echo "  devenv tasks run docs:serve           — Serve docs with live reload"
  '';

  # ── Tests ──────────────────────────────────────────────────────────────────
  enterTest = ''
    echo "=== Waiting for stack health ==="
    python3 scripts/wait_for_stack.py --stale-timeout 300

    echo ""
    echo "=== Tier-0: Component Health ==="
    uv run behave features/ --tags=@tier-0 --no-capture

    echo ""
    echo "=== Tier-1: Integration Tests ==="
    uv run behave features/ --tags=@tier-1 --no-capture

    echo ""
    echo "=== Running Impala FE unit tests ==="
    cd components/impala
    source bin/impala-config.sh
    mvn test -pl fe \
      -Dtest="ConfigLoaderTest,KuduMetaProviderTest,SignalsDdlExecutorTest" \
      -DfailIfNoTests=false --no-transfer-progress
  '';
}
