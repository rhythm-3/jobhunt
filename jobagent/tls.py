"""TLS context with a real CA bundle. python.org macOS builds ship without root certs, so prefer certifi."""
from __future__ import annotations

import ssl


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()      # system store; verification is never disabled
