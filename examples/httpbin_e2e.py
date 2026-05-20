# Copyright (c) 2026 Datanautics GmbH
# SPDX-License-Identifier: Apache-2.0
"""End-to-end verification: PassboltSecret → httpbin.org Basic auth.

Mimics the authentication flow that runs inside a KNIME Python Script node
downstream of the "Passbolt Credential to Python" bridge node, using a
Passbolt resource configured with::

    username = user987
    password = test123

against ``https://httpbin.org/basic-auth/user987/test123`` (which returns
HTTP 200 with ``{"authenticated": true, "user": "user987"}`` when Basic
auth credentials match the URL path components).

Two modes
---------

1. **Standalone** (no KNIME, no Passbolt). Runs an in-process mock broker
   on a loopback port that emits the same JSON shape the real Java broker
   does, then exercises the full PassboltSecret context-manager + wipe
   path and the httpbin.org call. Useful for local development and CI.

   ::

       python examples/httpbin_e2e.py

   Exits 0 on success, non-zero on any assertion failure. Needs the
   ``knime_passbolt`` package importable (``pip install -e .`` from the
   package root) and ``requests`` (``pip install requests``).

2. **KNIME Python Script node**. Paste the body of :func:`run_knime_side`
   into a Python Script node downstream of the bridge node. The bridge
   delivers ``knio.input_objects[0]`` as a ``PassboltSecret`` and the
   rest of the function works unchanged.

The standalone mock broker mimics three properties of the real one:
loopback bind, ``Bearer`` token gating, and the
``{"scheme": "Basic", "header": "<base64 user:pass>"}`` response shape.
It deliberately does NOT mimic constant-time token comparison — that's
a Java-side concern that the wrapper doesn't depend on.
"""

from __future__ import annotations

import base64
import http.server
import json
import sys
import threading

import requests

from knime_passbolt import PassboltSecret

USERNAME = "user987"
PASSWORD = "test123"
HTTPBIN_URL = f"https://httpbin.org/basic-auth/{USERNAME}/{PASSWORD}"

# 32-char minimum required by PassboltSecret.__init__.
TEST_TOKEN = "test-broker-token-base64url-3D3D3D3D3D3D"


def _basic_auth_payload(user: str, password: str) -> str:
    """Mimic Java's PassboltCredential.getAuthParameters(): base64 of user:pass."""
    return base64.b64encode(f"{user}:{password}".encode()).decode("ascii")


class _MockBrokerHandler(http.server.BaseHTTPRequestHandler):
    """Stub implementation of GET /v1/auth-header."""

    expected_token: str = ""
    user: str = ""
    password: str = ""

    def do_GET(self) -> None:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._respond(401, {"error": "unauthorized"})
            return
        if auth[len("Bearer ") :] != self.__class__.expected_token:
            self._respond(401, {"error": "unauthorized"})
            return
        self._respond(
            200,
            {
                "scheme": "Basic",
                "header": _basic_auth_payload(self.__class__.user, self.__class__.password),
            },
        )

    def _respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args, **kwargs) -> None:  # silence stderr noise
        return


def _start_mock_broker(
    user: str, password: str, token: str
) -> tuple[str, http.server.ThreadingHTTPServer]:
    _MockBrokerHandler.expected_token = token
    _MockBrokerHandler.user = user
    _MockBrokerHandler.password = password
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MockBrokerHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/v1/auth-header"
    return url, httpd


def run_knime_side(secret: PassboltSecret) -> dict:
    """Body of the Python Script node downstream of the bridge.

    Receives a ``PassboltSecret`` (in real KNIME use this is
    ``knio.input_objects[0]``), calls httpbin.org with the broker-fetched
    Basic header, and returns the parsed JSON response. Raises ``AssertionError``
    if httpbin doesn't confirm authentication.
    """
    with secret as cred:
        header_value = cred.basic_auth_header()
        response = requests.get(
            HTTPBIN_URL,
            headers={"Authorization": header_value.decode("ascii")},
            timeout=15,
        )
    # `with` exit → bytearray zeroed; subsequent calls would raise.
    response.raise_for_status()
    body = response.json()
    assert body == {"authenticated": True, "user": USERNAME}, (
        f"httpbin did not confirm auth: {body!r}"
    )
    return body


def main() -> int:
    print("Starting mock broker on a loopback port...")
    broker_url, httpd = _start_mock_broker(USERNAME, PASSWORD, TEST_TOKEN)
    print(f"  broker_url = {broker_url}")
    try:
        secret = PassboltSecret(
            broker_url=broker_url,
            token=TEST_TOKEN,
            session_uuid="test-session-00000000-0000-4000-8000-000000000000",
        )
        print(f"  repr before fetch: {secret!r}")

        body = run_knime_side(secret)
        print(f"  repr after with:   {secret!r}")
        print(f"  httpbin.org response: {body}")
        print("PASS: PassboltSecret authenticated successfully through httpbin.")

        # Double-wipe semantics: calling basic_auth_header() outside the
        # `with` (after wipe) must raise — proves the lifecycle contract.
        try:
            secret.basic_auth_header()
        except RuntimeError as ex:
            print(f"PASS: post-wipe call raised as expected — {ex}")
        else:
            print("FAIL: post-wipe call should have raised RuntimeError")
            return 1

        return 0

    finally:
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())
