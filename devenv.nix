{ pkgs, lib, config, inputs, ... }:

{
  dotenv.enable = true;

  # ── Packages ───────────────────────────────────────────────────────────────
  packages = with pkgs; [
    # Core
    git
    gh
    jq

    # Kerberos / Security
    krb5
    cyrus_sasl
    openssl_3

    # ASF build dependencies (Kudu, Impala)
    cmake
    ninja
    gcc
    protobuf
    flatbuffers

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
  env = {
    KRB5_REALM = "KRBTEST.COM";
    KRB5_KDC_PORT = "8848";
  };

  # ── PostgreSQL ─────────────────────────────────────────────────────────────
  services.postgres = {
    enable = true;
    package = pkgs.postgresql_16;
    extensions = extensions: [
      extensions.age
      extensions.pg_cron
    ];
    settings = {
      shared_preload_libraries = "age,pg_cron";
      "cron.database_name" = "signals";
    };
    initialDatabases = [{ name = "signals"; }];
    initialScript = ''
      CREATE EXTENSION IF NOT EXISTS age;
      LOAD 'age';
      SET search_path = ag_catalog, "$user", public;
      CREATE EXTENSION IF NOT EXISTS pg_cron;
    '';
  };

  # ── KDC Process ────────────────────────────────────────────────────────────
  processes.kdc.exec = ''
    # Initialize KDC if needed
    bash scripts/kdc-init.sh

    KDC_DIR="$PWD/.devenv/kdc"

    echo "Starting KDC on 127.0.0.1:''${KRB5_KDC_PORT:-8848}..."
    exec env \
      KRB5_CONFIG="$KDC_DIR/krb5.conf" \
      KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
      krb5kdc -n
  '';

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
  };

  # ── Shell ──────────────────────────────────────────────────────────────────
  enterShell = ''
    KDC_DIR="$PWD/.devenv/kdc"
    export KRB5_CONFIG="$KDC_DIR/krb5.conf"
    export KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf"
    export KRB5CCNAME="$KDC_DIR/krb5cc"

    # OpenTofu alias
    alias tf=tofu

    echo "signals-360 development environment"
    echo ""
    echo "Services (start with 'devenv up'):"
    echo "  PostgreSQL 16  — extensions: age, pg_cron"
    echo "  Kerberos KDC   — realm: KRBTEST.COM, port: 8848"
    echo ""
    echo "Tasks:"
    echo "  devenv tasks run signals:kdc-init    — Initialize KDC"
    echo "  devenv tasks run signals:kdc-reset   — Reset KDC database"
    echo "  devenv tasks run docs:build          — Build documentation"
    echo "  devenv tasks run docs:serve          — Serve docs with live reload"
  '';

  # ── Tests ──────────────────────────────────────────────────────────────────
  enterTest = ''
    echo "Running tests"
    git --version | grep --color=auto "${pkgs.git.version}"
  '';
}
