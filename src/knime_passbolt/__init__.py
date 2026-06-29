# Copyright (c) 2026 Datanautics GmbH
# SPDX-License-Identifier: Apache-2.0
"""knime-passbolt-py — Python-side wrapper for the KNIME Passbolt extension's
Credential-to-Python bridge node.

The bridge node in the `knime-passbolt` Java extension emits a pickled
:class:`PassboltSecret` instance on its output port. The Python Script node
consumes it via ``knio.input_objects[0]``. The credential itself stays in
the KNIME JVM; this wrapper holds only a short-lived loopback broker URL
and a bearer token, and fetches the Authorization-header value on demand.

Example
-------

.. code-block:: python

    import knime.scripting.io as knio
    import requests

    cred = knio.input_objects[0]
    with cred as c:
        h = c.basic_auth_header()
        resp = requests.get(url, headers={"Authorization": h.decode()})

The :class:`PassboltSecret` instance is a context manager: leaving the
``with`` block zeroes the bytearray that held the header value. Re-entering
the block triggers a fresh fetch from the broker.

Security properties
-------------------

- ``__slots__`` to prevent ``__dict__`` introspection of the wrapper.
- ``__repr__`` masks the underlying values.
- ``__reduce__`` re-pickles to the broker handshake only — credential bytes
  are never serialized.
- ``bytearray`` storage and best-effort zeroization via :func:`ctypes.memset`.
- The broker token is single-key (one bridge node → one token) and lives
  only as long as the bridge node's KNIME execution state.

Honest limits
-------------

In-process Python code can read the byte buffer while the ``with`` block is
open. CPython provides no hardware-enforced isolation. The bar is identical
to KNIME's own *Credentials Configuration* flow variable combined with a
disciplined helper class.
"""

# _build_from_broker is imported here so Java's hand-crafted pickle byte
# stream (which uses GLOBAL on the module path `knime_passbolt._build_from_broker`)
# can resolve it. Not part of the public API, hence not in __all__.
from knime_passbolt._secret import PassboltSecret, _build_from_broker  # noqa: F401

__all__ = ["PassboltSecret"]
__version__ = "0.1.1"
