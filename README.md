# knime-passbolt-py

Python wrapper for consuming Passbolt credentials in KNIME Python Script nodes,
via the **Credential to Python** bridge node shipped in the
[knime-passbolt](https://datanautics.net/) extension.

## Install

```bash
pip install knime-passbolt-py
```

## Usage

In a KNIME workflow, wire:

```
Passbolt Connector → Get Secret → Credential to Python → Python Script
```

In the Python Script node:

```python
import knime.scripting.io as knio
import requests

cred = knio.input_objects[0]            # PassboltSecret instance

with cred as c:                          # bytearray zeroed on __exit__
    h = c.basic_auth_header()
    resp = requests.get(url, headers={"Authorization": h.decode()})
```

## Security model

The credential lives in the **KNIME JVM**, in the existing in-memory
`CredentialCache` owned by the upstream Get Secret node. This wrapper carries
only a loopback broker URL (`http://127.0.0.1:<port>/v1/auth-header`) and a
short-lived bearer token. The Authorization header is fetched on demand,
held in a `bytearray`, and zeroed (`ctypes.memset`) when the `with` block
exits.

- `__slots__` prevents `__dict__` introspection.
- `__repr__` masks the broker URL only; never logs the token or any credential bytes.
- `__reduce__` re-pickles to the broker handshake — credential bytes are
  never serialized, even by accident.
- Broker URL is validated to be loopback at every fetch; tampering with a
  saved pickle to redirect to an external host is rejected client-side.

**Limits.** In-process Python code can read the bytearray while the `with`
block is open. CPython does not provide hardware-enforced isolation. The
posture is on par with KNIME's own *Credentials Configuration* flow variable
combined with a disciplined helper class — better is not achievable in
CPython without sandboxing.

## Compatibility

This package version (`0.1.0`) is compatible with the `knime-passbolt` KNIME extension version `0.1.1.20260520` and later. The full extension-↔-package compatibility matrix lives in [`CONTRACT.md`](./CONTRACT.md).

## License

Apache 2.0. See the `LICENSE` file shipped with this package, or
<https://www.apache.org/licenses/LICENSE-2.0>.

## About

`knime-passbolt-py` is published by [Datanautics GmbH](https://datanautics.net/)
as the companion Python package for the `knime-passbolt` KNIME extension.

Source: <https://github.com/DataNautics-GmbH/knime-passbolt-py>
Issues: <https://github.com/DataNautics-GmbH/knime-passbolt-py/issues>
