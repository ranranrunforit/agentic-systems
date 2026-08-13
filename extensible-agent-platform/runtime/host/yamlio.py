"""YAML loading for extension manifests and policy files.

Uses PyYAML when available. Falls back to a small parser covering the subset of
YAML the contract uses (nested mappings, block sequences, inline flow
maps/sequences, scalars, comments and block scalars) so the reference host runs
with a bare CPython install and no network access.

`runtime/tests/test_platform.py::TestContract` runs against whichever parser is
present, and `_selftest()` below asserts the fallback agrees with PyYAML on every
YAML file this repository ships.
"""

from __future__ import annotations

import json
import re
from typing import Any

try:  # pragma: no cover - environment dependent
    import yaml as _pyyaml
except Exception:  # pragma: no cover
    _pyyaml = None


def load(text: str) -> Any:
    if _pyyaml is not None:
        return _pyyaml.safe_load(text)
    return _MiniYaml(text).parse()


def load_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return load(fh.read())


def dump(obj: Any) -> str:
    if _pyyaml is not None:
        return _pyyaml.safe_dump(obj, sort_keys=False, default_flow_style=False)
    return json.dumps(obj, indent=2)  # JSON is a YAML subset


# --------------------------------------------------------------------------- #
# Minimal fallback parser
# --------------------------------------------------------------------------- #

_NUM = re.compile(r"^-?\d+(\.\d+)?$")
_BLOCK_HEADER = re.compile(r"^(-\s+)?([^:#]+):\s*([>|])([+-]?)\d*$")
_SENTINEL = "\x00blk:"


class _MiniYaml:
    def __init__(self, text: str) -> None:
        self.lines: list[tuple[int, str]] = []
        self.blocks: dict[str, str] = {}
        raw_lines = text.splitlines()
        i = 0
        while i < len(raw_lines):
            raw = raw_lines[i]
            i += 1
            stripped = _strip_comment(raw)
            if not stripped.strip() or stripped.strip() in ("---", "..."):
                continue
            indent = len(stripped) - len(stripped.lstrip(" "))
            body = stripped.strip()

            header = _BLOCK_HEADER.match(body)
            if header:
                # A block scalar: `description: >-`, `justification: |`, etc.
                # Its body is raw text, so comment stripping must not apply to it.
                dash, key, style, chomp = header.groups()
                block: list[str] = []
                while i < len(raw_lines):
                    nxt = raw_lines[i]
                    if nxt.strip():
                        nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                        if nxt_indent <= indent:
                            break
                    block.append(nxt)
                    i += 1
                value = _block_scalar(block, style, chomp)
                token = f"{_SENTINEL}{len(self.blocks)}"
                self.blocks[token] = value
                body = f"{dash or ''}{key}: {token}"

            self.lines.append((indent, body))
        self.pos = 0

    def _sc(self, text: str) -> Any:
        """Resolve a scalar, mapping block-scalar tokens back to their text."""
        token = text.strip()
        if token.startswith(_SENTINEL):
            return self.blocks[token]
        return _scalar(token)

    def parse(self) -> Any:
        if not self.lines:
            return None
        return self._parse_block(self.lines[0][0])

    def _peek(self):
        return self.lines[self.pos] if self.pos < len(self.lines) else None

    def _parse_block(self, indent: int) -> Any:
        item = self._peek()
        if item is None:
            return None
        if item[1].startswith("- "):
            return self._parse_seq(indent)
        return self._parse_map(indent)

    def _parse_seq(self, indent: int) -> list:
        out: list = []
        while True:
            item = self._peek()
            if item is None or item[0] < indent or not item[1].startswith("- "):
                return out
            self.pos += 1
            body = item[1][2:].strip()
            if ":" in body and not body.startswith(("{", "[")):
                # inline first key of a mapping item
                key, _, rest = body.partition(":")
                entry: dict[str, Any] = {}
                if rest.strip():
                    entry[key.strip()] = self._sc(rest.strip())
                else:
                    nxt = self._peek()
                    if nxt is not None and nxt[0] > indent and nxt[1][:1] in "[{":
                        self.pos += 1
                        entry[key.strip()] = self._sc(nxt[1])
                    elif nxt is not None and nxt[0] > indent:
                        entry[key.strip()] = self._parse_block(nxt[0])
                    else:
                        entry[key.strip()] = None
                while True:
                    nxt = self._peek()
                    if nxt is None or nxt[0] <= indent or nxt[1].startswith("- "):
                        break
                    entry.update(self._parse_map(nxt[0]))
                out.append(entry)
            else:
                out.append(self._sc(body))

    def _parse_map(self, indent: int) -> dict:
        out: dict[str, Any] = {}
        while True:
            item = self._peek()
            if item is None or item[0] < indent or item[1].startswith("- "):
                return out
            if item[0] > indent:  # unexpected deeper block: consume as nested
                out_key = list(out)[-1] if out else None
                nested = self._parse_block(item[0])
                if out_key is not None:
                    out[out_key] = nested
                continue
            self.pos += 1
            key, _, rest = item[1].partition(":")
            key = key.strip().strip('"').strip("'")
            rest = rest.strip()
            if rest:
                out[key] = self._sc(rest)
                continue
            nxt = self._peek()
            if nxt is not None and nxt[0] > indent and nxt[1][:1] in "[{":
                # a flow collection wrapped onto its own line:  action:\n  [a, b]
                self.pos += 1
                out[key] = self._sc(nxt[1])
            elif nxt is not None and nxt[0] > indent:
                out[key] = self._parse_block(nxt[0])
            elif nxt is not None and nxt[1].startswith("- ") and nxt[0] == indent:
                out[key] = self._parse_seq(indent)
            else:
                out[key] = None


def _block_scalar(raw_block: list[str], style: str, chomp: str) -> str:
    """Resolve a YAML block scalar body.

    `>` folds each paragraph onto one line and separates paragraphs with a
    newline; `|` keeps the line structure. `-` strips the trailing newline,
    which is what every manifest in this repository uses (`>-`).
    """
    lines = list(raw_block)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    common = min(len(ln) - len(ln.lstrip(" ")) for ln in lines if ln.strip())
    lines = [ln[common:] if ln.strip() else "" for ln in lines]

    if style == "|":
        text = "\n".join(lines)
    else:
        paragraphs: list[str] = []
        buffer: list[str] = []
        for line in lines:
            if line.strip():
                buffer.append(line.strip())
            else:
                paragraphs.append(" ".join(buffer))
                buffer = []
        paragraphs.append(" ".join(buffer))
        text = "\n".join(paragraphs)

    if chomp == "-":
        return text
    if chomp == "+":
        return text + "\n" * (1 + len(raw_block) - len(lines))
    return text + "\n"


def _strip_comment(line: str) -> str:
    out, in_s, quote = [], False, ""
    for ch in line:
        if in_s:
            out.append(ch)
            if ch == quote:
                in_s = False
            continue
        if ch in "\"'":
            in_s, quote = True, ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(text: str) -> Any:
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return _flow(text)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    low = text.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return None
    if _NUM.match(text):
        return float(text) if "." in text else int(text)
    return text


def _flow(text: str) -> Any:
    """Parse an inline flow collection: {a: 1, b: [x, y]} / [a, b]."""
    value, rest = _flow_value(text, 0)
    if rest.strip():
        raise ValueError(f"trailing content in flow scalar: {text!r}")
    return value


def _flow_value(text: str, i: int):
    while i < len(text) and text[i] == " ":
        i += 1
    if i < len(text) and text[i] == "{":
        out: dict[str, Any] = {}
        i += 1
        while True:
            while i < len(text) and text[i] in " ,":
                i += 1
            if i < len(text) and text[i] == "}":
                return out, text[i + 1 :]
            key_end = text.index(":", i)
            key = text[i:key_end].strip().strip("\"'")
            val, remainder = _flow_value(text, key_end + 1)
            out[key] = val
            i = len(text) - len(remainder)
    if i < len(text) and text[i] == "[":
        items: list[Any] = []
        i += 1
        while True:
            while i < len(text) and text[i] in " ,":
                i += 1
            if i < len(text) and text[i] == "]":
                return items, text[i + 1 :]
            val, remainder = _flow_value(text, i)
            items.append(val)
            i = len(text) - len(remainder)
    # plain scalar up to , } ]
    j = i
    depth = 0
    while j < len(text):
        ch = text[j]
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            break
        j += 1
    return _scalar(text[i:j]), text[j:]


def _selftest(paths: list[str]) -> int:  # pragma: no cover - developer tool
    """Assert the fallback parser agrees with PyYAML on real files.

        python3 -m runtime.host.yamlio integrations/*/extension.yaml ...
    """
    if _pyyaml is None:
        print("PyYAML not installed; nothing to compare against")
        return 0
    mismatches = 0
    for path in paths:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        if _pyyaml.safe_load(text) != _MiniYaml(text).parse():
            mismatches += 1
            print(f"MISMATCH {path}")
    print(f"checked {len(paths)} file(s), {mismatches} mismatch(es)")
    return 1 if mismatches else 0


if __name__ == "__main__":  # pragma: no cover
    import glob
    import sys

    args = sys.argv[1:] or (
        glob.glob("integrations/*/extension.yaml")
        + glob.glob("runtime/tests/fixtures/*/extension.yaml")
        + ["security/policy/abac-policy.yaml", "governance/approved-grants.yaml"]
    )
    raise SystemExit(_selftest(args))
