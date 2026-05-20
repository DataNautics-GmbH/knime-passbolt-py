# Copyright (c) 2026 Datanautics GmbH
# SPDX-License-Identifier: Apache-2.0
"""Read a password-protected Word (.docx) document using a Passbolt-stored password.

Use this as the body of a KNIME Python Script node wired downstream of:

    Passbolt Connector → Get Secret → Credential to Python

Plus an upstream File / Path Selector that emits the file path as the
``Location`` flow variable.

The Passbolt resource's *password* field holds the .docx password. The
*username* field is ignored.

Library installation, once per KNIME Python env::

    pip install msoffcrypto-tool

(The original draft of this example used ``python-docx``. Dropped because
``python-docx`` depends on ``lxml`` whose compiled-C extension is fragile
on Windows + KNIME's user-site-pip-install pattern. A ``.docx`` is just a
ZIP archive with XML payloads inside; the stdlib's ``zipfile`` +
``xml.etree.ElementTree`` parse it without any native dependencies.)

Word's encryption uses the MS-OFFCRYPTO container — same one Excel uses —
so we decrypt with ``msoffcrypto-tool`` into an in-memory buffer first,
then parse ``word/document.xml`` directly from the decrypted ZIP. The
plaintext document bytes never hit disk.

Path handling
-------------

KNIME's Python Script node has its CWD at the workspace root, not the
workflow data area, so relative paths emitted by a File Selector in
"Relative to: Workflow Data Area" mode (e.g. ``./secured file.docx``)
do NOT resolve correctly with Python's standard CWD-based
``os.path.abspath``.

:func:`resolve_file_path` resolves relative paths by walking ONLY the
workspace's category tree (stopping at each workflow root, identified
by the presence of a ``workflow.knime`` file) and probing
``<workflow>/data/<rel-path>`` directly — workflow internals (node
sub-directories with their port-data files) are never entered, which
is the difference between sub-second resolution and a multi-second
walk on a populated workspace.

Output table::

    paragraph | style | text

For richer extraction (tables, headings, lists, runs) extend the loop —
``ElementTree`` exposes every element in the document, and the
WordprocessingML namespace is well-documented.
"""

import base64
import io
import os
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import knime.scripting.io as knio
import msoffcrypto
import pandas as pd

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Directory-name prefixes to prune during the workspace walk. Hidden dirs
# (.git, .metadata, .knime, …), Python build/cache dirs, and obvious temp
# locations are skipped — they never contain workflow roots.
_PRUNED_DIR_PREFIXES = (".", "node_modules", "__pycache__", "tmp", "temp")


def resolve_file_path(path_str: str) -> str:
    """Resolve ``path_str`` to an absolute, existing file path.

    Strategy:

    1. Absolute path → must exist as-is, else raise.
    2. Relative path & found at ``CWD/path`` → use that.
    3. Relative path → walk only the *category tree* of the KNIME
       workspace (``knime.workspace`` flow variable) looking for
       directories that contain a ``workflow.knime`` marker file. At
       each workflow root, probe ``<workflow>/data/<rel-path>`` once.
       The walk NEVER descends into a workflow's internals — those
       per-node subdirectories hold most of a workspace's directory
       entries and contribute zero useful candidates.

    KNIME's File Selector "Relative to: Workflow Data Area" emits paths
    like ``./foo.docx`` where ``./`` is the workflow data area; the
    actual file therefore lives at ``<workflow>/data/foo.docx``.
    """
    p = Path(path_str)

    if p.is_absolute():
        if not p.is_file():
            raise FileNotFoundError(f"File not found at {path_str!r}.")
        return str(p)

    cwd_resolved = p.resolve()
    if cwd_resolved.is_file():
        return str(cwd_resolved)

    workspace = knio.flow_variables.get("knime.workspace", "")
    if not workspace or not os.path.isdir(workspace):
        raise FileNotFoundError(
            f"Cannot resolve relative path {path_str!r}: workspace {workspace!r} not accessible."
        )

    # Strip the leading "./" — the relative path is relative to the data
    # area itself, so the file lives at `<workflow>/data/<this>`. Use
    # removeprefix (Py 3.9+) rather than lstrip — lstrip treats "./" as
    # a *set of characters* and would collapse "..foo.pdf" to "foo.pdf".
    target_rel = os.path.normpath(path_str).replace("\\", "/")
    for prefix in ("./", "../"):
        while target_rel.startswith(prefix):
            target_rel = target_rel[len(prefix) :]
    target_rel = target_rel.lstrip("/")
    target_parts = target_rel.split("/")

    workspace_norm = os.path.normpath(workspace)

    for root, dirs, files in os.walk(workspace_norm):
        if "workflow.knime" in files:
            # Workflow root — probe target and stop descending.
            candidate = os.path.join(root, "data", *target_parts)
            if os.path.isfile(candidate):
                return candidate
            dirs[:] = []  # never recurse into a workflow's node dirs
            continue
        # Non-workflow level — prune hidden / temp dirs and keep walking.
        dirs[:] = [d for d in dirs if not d.startswith(_PRUNED_DIR_PREFIXES)]

    raise FileNotFoundError(
        f"No file matching {path_str!r} found at <any-workflow>/data/"
        f"{target_rel!r} under workspace {workspace_norm!r}."
    )


def extract_paragraphs(docx_bytes: io.BytesIO):
    """Yield (style_name, text) for each non-empty paragraph in the .docx bytes.

    Uses stdlib only — no python-docx / lxml dependency. Reads
    ``word/document.xml`` from the ZIP and walks ``<w:p>`` elements.
    """
    with zipfile.ZipFile(docx_bytes, "r") as zf, zf.open("word/document.xml") as f:
        tree = ET.parse(f)

    for paragraph in tree.iter(f"{{{W_NS}}}p"):
        # Style: <w:pPr><w:pStyle w:val="StyleName"/></w:pPr>
        style = ""
        ppr = paragraph.find(f"{{{W_NS}}}pPr")
        if ppr is not None:
            pstyle = ppr.find(f"{{{W_NS}}}pStyle")
            if pstyle is not None:
                style = pstyle.get(f"{{{W_NS}}}val", "")

        # Text: concatenate all <w:t> descendants (handles split runs).
        text = "".join(t.text or "" for t in paragraph.iter(f"{{{W_NS}}}t"))

        if text.strip():
            yield style, text


cred = knio.input_objects[0]
docx_path = resolve_file_path(knio.flow_variables["Location"])

with cred as c:
    header = c.basic_auth_header()
    _, b64 = header.split(b" ", 1)
    _user, _, password = base64.b64decode(b64).decode("utf-8").partition(":")

    # Decrypt MS-OFFCRYPTO container into a memory buffer.
    decrypted = io.BytesIO()
    with open(docx_path, "rb") as fin:
        office = msoffcrypto.OfficeFile(fin)
        try:
            office.load_key(password=password)
        except msoffcrypto.exceptions.InvalidKeyError:
            raise ValueError(
                "Wrong password for .docx — the Passbolt resource's password "
                "field does not match the document's encryption password."
            ) from None
        office.decrypt(decrypted)
    decrypted.seek(0)

    rows = [
        {"paragraph": i, "style": style, "text": text}
        for i, (style, text) in enumerate(extract_paragraphs(decrypted), start=1)
    ]

knio.output_tables[0] = knio.Table.from_pandas(pd.DataFrame(rows))
