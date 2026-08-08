"""Impala HS2 connection — Kerberos GSSAPI only (no NOSASL fallback).

Product path: dial $SIGNALS_KRB_HOST / $IMPALA_HS2_HOST (FQDN), never loopback,
so the SPN is impala/<fqdn>@REALM matching .devenv/kdc/impala.keytab.
"""

from __future__ import annotations

import os
from typing import Any


def _krb_host() -> str:
    return (
        os.environ.get("IMPALA_HS2_HOST")
        or os.environ.get("SIGNALS_KRB_HOST")
        or "tinybox.dev.vista.zndx.org"
    )


def _ensure_krb_env() -> None:
    """Point MIT krb5 at devenv KDC when running from repo root."""
    if not os.environ.get("KRB5CCNAME") and os.path.isdir(".devenv/kdc"):
        os.environ.setdefault("KRB5CCNAME", os.path.abspath(".devenv/kdc/krb5cc"))
    if not os.environ.get("KRB5_CONFIG") and os.path.isfile(".devenv/kdc/krb5.conf"):
        os.environ.setdefault(
            "KRB5_CONFIG", os.path.abspath(".devenv/kdc/krb5.conf")
        )


def impala_connect(
    host: str | None = None,
    port: int | None = None,
    **kwargs: Any,
):
    """Connect to Impala HS2 with GSSAPI. Raises if host is loopback or auth fails."""
    _ensure_krb_env()
    h = host or _krb_host()
    if h in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(
            f"Impala host {h!r} is loopback — Kerberos SPN would be wrong. "
            f"Use FQDN ($SIGNALS_KRB_HOST / $IMPALA_HS2_HOST), run: just kinit"
        )
    p = int(port if port is not None else os.environ.get("IMPALA_HS2_PORT", "21050"))
    service = os.environ.get("IMPALA_KERBEROS_SERVICE", "impala")

    # Hard-require GSSAPI — ignore any caller auth_mechanism=NOSASL
    kwargs.pop("auth_mechanism", None)
    kwargs.pop("kerberos_service_name", None)

    from impala.dbapi import connect

    return connect(
        host=h,
        port=p,
        auth_mechanism="GSSAPI",
        kerberos_service_name=service,
        use_ssl=False,
        **kwargs,
    )
