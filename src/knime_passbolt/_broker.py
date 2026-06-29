# Copyright (c) 2026 Datanautics GmbH
# SPDX-License-Identifier: Apache-2.0
"""Loopback HTTP client for the KNIME-Passbolt extension's secret broker.

The broker server is hosted inside the KNIME JVM by the Credential-to-Python
bridge node. It binds to ``127.0.0.1`` on a random port and serves a single
endpoint: ``GET /v1/auth-header`` gated by a ``Bearer`` token. The Python
wrapper uses this module to fetch the resolved Authorization header value
when the user invokes :meth:`PassboltSecret.basic_auth_header`.

Stdlib-only (``urllib``) to keep the wrapper's dependency surface minimal.
"""

from __future__ import annotations

import json
from urllib import error, request


class BrokerError(RuntimeError):
    """Raised when the broker rejects a request or is unreachable."""


# The auth-header JSON is tiny (a scheme string + a base64 payload). Cap the
# read so a malicious/buggy loopback service can't exhaust memory.
_MAX_RESPONSE_BYTES = 64 * 1024

# Single source of truth for the loopback host allow-list, shared by the
# construction-time guard (PassboltSecret.__init__) and the request-time guard
# (_require_loopback) so the two cannot drift apart.
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def fetch_auth_header(broker_url: str, token: str, timeout: float = 5.0) -> tuple[str, str]:
    """Fetch the ``(scheme, header_value)`` pair from the broker.

    Parameters
    ----------
    broker_url:
        Loopback URL emitted by the bridge node, e.g.
        ``http://127.0.0.1:54321/v1/auth-header``.
    token:
        Bearer token minted by the bridge node.
    timeout:
        Per-request timeout in seconds. Default 5s; loopback round-trips
        are sub-millisecond, so anything longer indicates a malfunction.

    Returns
    -------
    ``(scheme, header_value)`` — for Passbolt-sourced credentials the scheme
    is ``"Basic"`` and ``header_value`` is the base64-encoded ``user:pass``
    payload (without the ``"Basic "`` prefix).

    Raises
    ------
    BrokerError
        If the URL is not a loopback URL, the broker returns a non-200
        status, the response is not the expected JSON shape, or the
        request times out.
    """
    _require_loopback(broker_url)

    req = request.Request(
        broker_url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Host": "127.0.0.1",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            # Read one byte past the cap so we can detect an over-long body.
            body_bytes = resp.read(_MAX_RESPONSE_BYTES + 1)
            if len(body_bytes) > _MAX_RESPONSE_BYTES:
                raise BrokerError("Passbolt broker returned an oversized response")
    except error.HTTPError as e:
        # Map 401/404 to specific, actionable messages without exposing internals.
        if e.code == 401:
            raise BrokerError(
                "Passbolt broker rejected the token. The bridge node has been "
                "reset, KNIME has restarted, or the token is stale. Re-execute "
                "the bridge node upstream."
            ) from None
        if e.code == 404:
            raise BrokerError(
                "Passbolt credential is no longer available in the KNIME "
                "cache. Re-execute the Get Secret node upstream."
            ) from None
        raise BrokerError(f"Passbolt broker returned HTTP {e.code}") from None
    except (error.URLError, TimeoutError, OSError) as e:
        raise BrokerError(f"Passbolt broker is not reachable: {e}") from None
    except ValueError:
        # urllib rejects malformed header values (e.g. CRLF in the token) with
        # ValueError. Tokens are validated upstream in PassboltSecret.__init__,
        # but map it here too so the contract "failures are BrokerError" holds.
        raise BrokerError("Passbolt broker request was malformed") from None

    if status != 200:
        raise BrokerError(f"Passbolt broker returned HTTP {status}")

    try:
        body = json.loads(body_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise BrokerError("Passbolt broker returned malformed response") from None

    scheme = body.get("scheme")
    header = body.get("header")
    if not isinstance(scheme, str) or not isinstance(header, str):
        raise BrokerError("Passbolt broker returned malformed response")
    return scheme, header


def _require_loopback(url: str) -> None:
    """Refuse to talk to anything other than 127.0.0.1 / ::1 / localhost.

    Defends against a malicious or buggy pickle that points the wrapper at
    an external URL. The bridge node always emits a loopback URL, so this
    check should never fail under normal operation — but it catches the
    case where the pickle was tampered with on disk between save and load.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "http":
        raise BrokerError(f"Broker URL must use http (got {parsed.scheme!r})")
    host = parsed.hostname
    if host not in _LOOPBACK_HOSTS:
        raise BrokerError(f"Broker URL must be loopback (got host {host!r})")
