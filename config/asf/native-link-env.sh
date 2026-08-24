# asf-signals — portable native link env for Impala/Kudu (and similar) under devenv/Nix.
# Sourced by devenv tasks and scripts/impala-build-isolated.sh.
#
# Problem: bare -lgssapi_krb5 fails with gold when libkrb5 is a full Nix path and
# there is no matching -L (rpath is runtime-only). Fix is full-path CMake targets
# (FindKerberos) plus LIBRARY_PATH / CMAKE_*_PATH so discovery is deterministic.
#
# Optional overrides: SIG_KRB5_LIB, SIG_KRB5_INC, SIG_SASL_LIB, SIG_SSL_LIB, …

_asf_prepend() {
  local var="$1"
  local val="$2"
  [ -z "$val" ] || [ ! -e "$val" ] && return 0
  eval "local cur=\"\${$var:-}\""
  case ":$cur:" in
    *":$val:"*) ;;
    *) export "$var=$val${cur:+:$cur}" ;;
  esac
}

# Prefer explicit SIG_* (set by devenv.nix from pkgs.*), then pkg-config, then leave alone.
if [ -z "${SIG_KRB5_LIB:-}" ] && command -v pkg-config >/dev/null 2>&1; then
  if pkg-config --exists mit-krb5 2>/dev/null; then
    SIG_KRB5_LIB="$(pkg-config --variable=libdir mit-krb5 2>/dev/null || true)"
    SIG_KRB5_INC="$(pkg-config --variable=includedir mit-krb5 2>/dev/null || true)"
  elif pkg-config --exists krb5 2>/dev/null; then
    SIG_KRB5_LIB="$(pkg-config --variable=libdir krb5 2>/dev/null || true)"
    SIG_KRB5_INC="$(pkg-config --variable=includedir krb5 2>/dev/null || true)"
  fi
fi

# Ensure gssapi is visible next to krb5 for find_library / -L
if [ -n "${SIG_KRB5_LIB:-}" ]; then
  _asf_prepend LIBRARY_PATH "$SIG_KRB5_LIB"
  _asf_prepend CMAKE_LIBRARY_PATH "$SIG_KRB5_LIB"
  _asf_prepend LD_LIBRARY_PATH "$SIG_KRB5_LIB"
  # Link-time search for any remaining bare -l flags
  case " ${LDFLAGS:-} " in
    *" -L${SIG_KRB5_LIB} "*) ;;
    *) export LDFLAGS="-L${SIG_KRB5_LIB} ${LDFLAGS:-}" ;;
  esac
  # Help FindKerberos when includes live in a split -dev store path
  if [ -n "${SIG_KRB5_INC:-}" ]; then
    _asf_prepend CMAKE_INCLUDE_PATH "$SIG_KRB5_INC"
    _asf_prepend CPATH "$SIG_KRB5_INC"
  fi
  # KRB5_ROOT: lib dir parent often works; also export lib dir for HINTS
  if [ -z "${KRB5_ROOT:-}" ]; then
    export KRB5_ROOT="$(cd "${SIG_KRB5_LIB}/.." 2>/dev/null && pwd || echo "${SIG_KRB5_LIB}")"
  fi
fi

if [ -z "${SIG_SASL_INC:-}" ] && [ -n "${SIG_SASL_LIB:-}" ]; then
  if [ -f "${SIG_SASL_LIB}/../include/sasl/sasl.h" ]; then
    SIG_SASL_INC="$(cd "${SIG_SASL_LIB}/../include" && pwd)"
  fi
fi
if [ -z "${SIG_SASL_INC:-}" ]; then
  for _sasl_h in /usr/include/sasl/sasl.h \
                 "${ROOT:-}/.devenv/profile/include/sasl/sasl.h" \
                 /nix/store/*cyrus-sasl*-dev/include/sasl/sasl.h; do
    if [ -f "$_sasl_h" ]; then
      SIG_SASL_INC="$(cd "$(dirname "$_sasl_h")/.." && pwd)"
      break
    fi
  done
  unset _sasl_h
fi
if [ -n "${SIG_SASL_LIB:-}" ]; then
  _asf_prepend LIBRARY_PATH "$SIG_SASL_LIB"
  _asf_prepend CMAKE_LIBRARY_PATH "$SIG_SASL_LIB"
  case " ${LDFLAGS:-} " in *" -L${SIG_SASL_LIB} "*) ;; *) export LDFLAGS="-L${SIG_SASL_LIB} ${LDFLAGS:-}" ;; esac
fi
if [ -n "${SIG_SASL_INC:-}" ]; then
  _asf_prepend CMAKE_INCLUDE_PATH "$SIG_SASL_INC"
  _asf_prepend CPATH "$SIG_SASL_INC"
  _asf_prepend CPLUS_INCLUDE_PATH "$SIG_SASL_INC"
  case " ${CPPFLAGS:-} " in *" -I${SIG_SASL_INC} "*) ;; *) export CPPFLAGS="-I${SIG_SASL_INC} ${CPPFLAGS:-}" ;; esac
  export SIG_SASL_INC
fi
if [ -n "${SIG_SSL_LIB:-}" ]; then
  _asf_prepend LIBRARY_PATH "$SIG_SSL_LIB"
  _asf_prepend CMAKE_LIBRARY_PATH "$SIG_SSL_LIB"
  case " ${LDFLAGS:-} " in *" -L${SIG_SSL_LIB} "*) ;; *) export LDFLAGS="-L${SIG_SSL_LIB} ${LDFLAGS:-}" ;; esac
fi

# Multiarch system libs (librt, libdl) — APPEND so SIG_SSL/KRB5 stay preferred for
# find_library (prepending caused OpenSSL headers from Nix + libs from /lib → link fail).
_asf_append() {
  local var="$1"
  local val="$2"
  [ -z "$val" ] || [ ! -e "$val" ] && return 0
  eval "local cur=\"\${$var:-}\""
  case ":$cur:" in
    *":$val:"*) ;;
    *) export "$var=${cur:+$cur:}$val" ;;
  esac
}
for _syslib in /usr/lib/x86_64-linux-gnu /lib/x86_64-linux-gnu /usr/lib64 /usr/lib; do
  _asf_append CMAKE_LIBRARY_PATH "$_syslib"
  _asf_append LIBRARY_PATH "$_syslib"
done

# CMake FindOpenSSL respects OPENSSL_ROOT_DIR when set
if [ -n "${SIG_SSL_LIB:-}" ] && [ -z "${OPENSSL_ROOT_DIR:-}" ]; then
  export OPENSSL_ROOT_DIR="$(cd "${SIG_SSL_LIB}/.." 2>/dev/null && pwd || true)"
fi

export LIBRARY_PATH CMAKE_LIBRARY_PATH LD_LIBRARY_PATH CMAKE_INCLUDE_PATH CPATH LDFLAGS
unset -f _asf_prepend _asf_append
