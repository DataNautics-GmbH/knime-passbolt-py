# Copyright (c) 2026 Datanautics GmbH
# SPDX-License-Identifier: Apache-2.0
"""PassboltSecret wrapper class.

Constructed on the Python side by ``pickle.load`` calling the module-level
:func:`_build_from_broker` factory. The KNIME-side Java code emits a
pickle byte stream pointing at this function; nothing else in this module
is intended to be called by user code directly except :class:`PassboltSecret`.
"""

from __future__ import annotations

import ctypes

from knime_passbolt._broker import fetch_auth_header


class PassboltSecret:
    """Lazy, wipeable wrapper around a Passbolt-resolved credential.

    The instance carries only a loopback broker URL, a bearer token, and an
    opaque session UUID — never the credential bytes. The Authorization
    header is fetched from the broker the first time :meth:`basic_auth_header`
    is invoked inside a ``with`` block, stored in a :class:`bytearray`, and
    overwritten with zeros when the block exits.

    Intended use::

        with secret as cred:
            h = cred.basic_auth_header()
            requests.get(url, headers={"Authorization": h.decode()})

    Direct attribute access on the broker URL / token / session UUID is
    deliberately kept ``protected``-style (``_broker_url``, etc.) to signal
    "internal" to readers; ``__slots__`` prevents adding ad-hoc attributes
    on instances.
    """

    __slots__ = ("_broker_url", "_buf", "_session_uuid", "_token", "_wiped")

    # -- construction ------------------------------------------------------

    def __init__(self, broker_url: str, token: str, session_uuid: str) -> None:
        # Validate at construction so a malformed pickle surfaces here, not at
        # first use. None of these strings are secret in themselves.
        if not isinstance(broker_url, str) or not broker_url.startswith("http://127.0.0.1:"):
            raise ValueError("broker_url must be a loopback http URL")
        if not isinstance(token, str) or len(token) < 32:
            raise ValueError("token must be a non-trivial string")
        if not isinstance(session_uuid, str):
            raise ValueError("session_uuid must be a string")
        self._broker_url = broker_url
        self._token = token
        self._session_uuid = session_uuid
        self._buf: bytearray | None = None
        self._wiped = False

    # -- pickle ------------------------------------------------------------

    def __reduce__(self) -> tuple[object, tuple[str, str, str]]:
        """Re-pickle via the same factory the Java bridge uses.

        Returning ``(_build_from_broker, (...))`` means that even if user
        code accidentally calls ``pickle.dumps(secret)``, the resulting
        bytes contain only the broker handshake — never any credential.
        The buffer state (``_buf``, ``_wiped``) is intentionally dropped:
        re-loading creates a fresh, un-fetched wrapper.
        """
        return (_build_from_broker, (self._broker_url, self._token, self._session_uuid))

    # -- safe repr ---------------------------------------------------------

    def __repr__(self) -> str:
        return (
            "<PassboltSecret "
            f"broker={self._broker_url} "
            f"session={self._session_uuid[:8]}... "
            f"wiped={self._wiped}>"
        )

    def __str__(self) -> str:
        return self.__repr__()

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> PassboltSecret:
        if self._wiped:
            raise RuntimeError("PassboltSecret has been wiped; re-execute the bridge node")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.wipe()
        # never suppress exceptions
        return None

    # -- accessors ---------------------------------------------------------

    def basic_auth_header(self) -> bytes:
        """Return the full ``Authorization`` header value as bytes.

        Format: ``b"Basic <base64-encoded-user:pass>"``. Suitable for
        passing directly as ``headers={"Authorization": value.decode()}``.

        The header bytes are stored in an internal :class:`bytearray` so
        that :meth:`wipe` (and the context manager's ``__exit__``) can
        overwrite them in place. Calling this method multiple times within
        the same ``with`` block returns the same bytearray — only one
        broker round-trip per scope.
        """
        if self._wiped:
            raise RuntimeError("PassboltSecret has been wiped; re-execute the bridge node")
        if self._buf is not None:
            return bytes(self._buf)

        scheme, header_value = fetch_auth_header(self._broker_url, self._token)
        # Compose "<scheme> <header_value>". For Passbolt the scheme is "Basic".
        composed = f"{scheme} {header_value}".encode("ascii")
        self._buf = bytearray(composed)
        # Best-effort: scrub the intermediate `composed` bytes object. Bytes
        # objects are immutable; we can't directly zero it. The GC will
        # collect it; this is the unavoidable CPython limitation.
        del composed
        return bytes(self._buf)

    def session_uuid(self) -> str:
        """Opaque session UUID. Useful for log correlation, not for auth."""
        return self._session_uuid

    # -- wipe --------------------------------------------------------------

    def wipe(self) -> None:
        """Zero the internal bytearray and mark the wrapper unusable.

        Idempotent. Called automatically by the context manager's ``__exit__``.
        Uses :func:`ctypes.memset` on the bytearray's underlying buffer for a
        best-effort guarantee; CPython provides no stronger primitive.
        """
        if self._buf is not None:
            try:
                # bytearray's buffer is a contiguous block. ctypes.memset
                # overwrites it in place. Address-of-array returns a void*
                # to the first byte.
                length = len(self._buf)
                if length > 0:
                    addr = (ctypes.c_char * length).from_buffer(self._buf)
                    ctypes.memset(addr, 0, length)
            except (TypeError, ValueError):
                # Fallback if from_buffer is unavailable on this CPython build.
                for i in range(len(self._buf)):
                    self._buf[i] = 0
            self._buf = None
        self._wiped = True


def _build_from_broker(broker_url: str, token: str, session_uuid: str) -> PassboltSecret:
    """Pickle factory function.

    The KNIME-Passbolt Java extension emits a pickle byte stream whose
    ``REDUCE`` opcode calls this function with three positional arguments.
    Keeping the factory at module top level (rather than a classmethod)
    ensures the pickle ``GLOBAL`` opcode resolves it via a stable
    ``module.attribute`` lookup.
    """
    return PassboltSecret(broker_url=broker_url, token=token, session_uuid=session_uuid)
