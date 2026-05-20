# Bridge contract

`knime-passbolt-py` and the [`knime-passbolt`](https://github.com/mikeg-de/knime-passbolt) KNIME extension communicate through a hand-crafted pickle byte stream emitted by the Java side and deserialised by `pickle.load` on the Python side. The byte format is a **stable contract** that both sides must honour.

## Pickle format (pickle protocol 2)

The emitter produces:

```
\x80 \x02                                  PROTO 2
c knime_passbolt \n _build_from_broker \n  GLOBAL → factory function
X <4-byte LE len> <utf-8 bytes>            BINUNICODE → broker_url
X <4-byte LE len> <utf-8 bytes>            BINUNICODE → token
X <4-byte LE len> <utf-8 bytes>            BINUNICODE → session_uuid
\x87                                       TUPLE3
R                                          REDUCE → call(*args)
.                                          STOP
```

## Function signature (Python side)

```python
def _build_from_broker(broker_url: str, token: str, session_uuid: str) -> PassboltSecret:
    ...
```

The module path is **`knime_passbolt._build_from_broker`**, not `knime_passbolt._secret._build_from_broker`. The `__init__.py` re-exports the function (with `# noqa: F401`) so the pickle `GLOBAL` opcode finds it at the canonical location.

## Compatibility matrix

| Extension version | knime-passbolt-py version | Broker URL | Argument order |
|---|---|---|---|
| `0.1.1.20260520+` | `0.1.0+` | `http://127.0.0.1:<port>/v1/auth-header` | `(broker_url, token, session_uuid)` |

A new entry is added here on every change to the byte format, the function signature, the URL path, or the broker response shape.

## How to change the contract safely

1. **Additive changes only across one minor version.** Adding a 4th argument to `_build_from_broker` requires releasing the Python side first (accepts the new arg with a default) before the Java side starts emitting it.
2. **Breaking changes require a major bump on BOTH sides simultaneously**, plus an updated row in the matrix.
3. **Test cross-version compatibility** — run the latest Python-side wrapper against the previous Java-side emitter and vice versa before tagging.

## Producer and consumer source locations

- **Producer (Java):** `org.knime.ext.passbolt.python.PythonPickleEmitter` in `mikeg-de/knime-passbolt`.
- **Consumer (Python):** `_build_from_broker(broker_url, token, session_uuid)` in `src/knime_passbolt/_secret.py` (re-exported by `src/knime_passbolt/__init__.py`).

## Where to file bugs

- **Broker / JVM-side issues:** [`mikeg-de/knime-passbolt`](https://github.com/mikeg-de/knime-passbolt) issue tracker.
- **`PassboltSecret` / Python-wrapper issues:** this repo's issue tracker.
- **Cross-repo issues** (contract drift, version-pair mismatch): file in both, cross-link, tag `cross-repo`.
