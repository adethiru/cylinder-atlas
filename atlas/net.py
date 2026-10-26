"""HTTPS trust store that works on a fresh Mac.

The python.org macOS installer ships without CA certificates (you would normally
run 'Install Certificates.command'), which makes every HTTPS call fail with
CERTIFICATE_VERIFY_FAILED. We add the operating system's bundle (/etc/ssl/cert.pem
on macOS, common Linux paths) and certifi if it happens to be installed, so the
app works with zero setup while still verifying certificates."""
from __future__ import annotations

import os
import ssl

_CANDIDATES = ["/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
               "/usr/local/etc/openssl/cert.pem", "/opt/homebrew/etc/openssl@3/cert.pem"]
_CTX = None


def ssl_context() -> ssl.SSLContext:
    global _CTX
    if _CTX is None:
        ctx = ssl.create_default_context()
        try:
            import certifi  # optional
            ctx.load_verify_locations(certifi.where())
        except Exception:  # noqa: BLE001
            pass
        for p in _CANDIDATES:
            if os.path.exists(p):
                try:
                    ctx.load_verify_locations(p)
                except Exception:  # noqa: BLE001
                    pass
        _CTX = ctx
    return _CTX
