#!/usr/bin/env python3
"""Draft response types from recorded responses (V1812-OPENAPI-TYPES).

Reads the JSONL samples written by tests/response_recorder.py, merges every
route's bodies into one shape, and reports:

* coverage: JSON routes with and without samples;
* structure: distinct object shapes by field set, and which shapes recur
  across routes (candidates for one shared type);
* a draft module of TypedDicts (``--emit``), one per distinct shape, with a
  field marked NotRequired when some sample lacked it.

The draft is a starting point for review, not a generated contract: names,
shared types and the depth at which a payload stays ``dict[str, Any]`` are
decisions made when the draft is adopted.

Usage: python3 scripts/infer_response_types.py <samples-dir> [--emit out.py]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAP_MIN_KEYS = 24
_SCHEMA_KEYWORDS = frozenset({
    "type", "properties", "required", "items", "enum", "const", "minimum", "maximum", "minLength", "maxLength",
    "minItems", "maxItems", "uniqueItems", "additionalProperties", "description", "title", "default", "format",
    "pattern", "anyOf", "oneOf", "allOf", "$ref", "$defs", "examples", "exclusiveMinimum", "exclusiveMaximum",
})
_DATA_KEY = re.compile(r"[/:.\s]|^[0-9a-f]{8,}|^\d|^(?:run|nb|oprec|agent|trace|draft|opt|model|node|artifact)_[0-9a-z]{6,}")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class Shape:
    kinds: set[str] = field(default_factory=set)
    samples: int = 0
    fields: dict[str, "Shape"] = field(default_factory=dict)
    present: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    objects: int = 0
    items: "Shape | None" = None
    values: "Shape | None" = None  # objects used as maps keyed by data

    def add(self, value: Any) -> None:
        self.samples += 1
        if value is None:
            self.kinds.add("null")
        elif isinstance(value, bool):
            self.kinds.add("bool")
        elif isinstance(value, int):
            self.kinds.add("int")
        elif isinstance(value, float):
            self.kinds.add("float")
        elif isinstance(value, str):
            self.kinds.add("str")
        elif isinstance(value, list):
            self.kinds.add("list")
            self.items = self.items or Shape()
            for item in value:
                self.items.add(item)
        elif isinstance(value, dict):
            if value and (len(value) >= MAP_MIN_KEYS or all(_DATA_KEY.search(key) for key in value)):
                self.kinds.add("map")
                self.values = self.values or Shape()
                for item in value.values():
                    self.values.add(item)
            else:
                self.kinds.add("object")
                self.objects += 1
                for key, item in value.items():
                    self.fields.setdefault(key, Shape()).add(item)
                    self.present[key] += 1

    def signature(self) -> str:
        return ",".join(sorted(self.fields))


def load(directory: Path) -> dict[tuple[str, str], Shape]:
    shapes: dict[tuple[str, str], Shape] = {}
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            shapes.setdefault((record["method"], record["route"]), Shape()).add(record["body"])
    return shapes


def walk(shape: Shape, origin: str, found: list[tuple[str, Shape]]) -> None:
    if "object" in shape.kinds and shape.fields:
        found.append((origin, shape))
        for name, child in shape.fields.items():
            walk(child, f"{origin}.{name}", found)
    if shape.items:
        walk(shape.items, f"{origin}[]", found)
    if shape.values:
        walk(shape.values, f"{origin}{{}}", found)


def _class_name(origin: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", origin)
    return "".join(word[:1].upper() + word[1:] for word in words if word not in {"GET", "POST", "PUT", "PATCH", "DELETE"}) or "Root"


def _is_schema(shape: Shape) -> bool:
    return bool(shape.fields) and set(shape.fields) <= _SCHEMA_KEYWORDS and "type" in shape.fields | {"properties": None}


def emit(shapes: dict[tuple[str, str], Shape], max_depth: int = 99) -> str:
    names: dict[str, str] = {}
    classes: list[str] = []

    def annotation(shape: Shape, origin: str, depth: int = 0) -> str:
        parts: list[str] = []
        kinds = shape.kinds - {"null"}
        if kinds == {"int", "float"}:
            kinds = {"float"}
        for kind in sorted(kinds):
            if kind in {"bool", "int", "float", "str"}:
                parts.append(kind)
            elif kind == "list":
                inner = annotation(shape.items, origin + "Item", depth) if shape.items and shape.items.kinds else "Any"
                parts.append(f"list[{inner}]")
            elif kind == "map":
                inner = annotation(shape.values, origin + "Value", depth) if shape.values and shape.values.kinds else "Any"
                parts.append(f"dict[str, {inner}]")
            elif kind == "object":
                if _is_schema(shape):
                    parts.append("JsonSchema")
                elif not shape.fields or depth >= max_depth:
                    parts.append("dict[str, Any]")
                else:
                    parts.append(declare(shape, origin, depth))
        text = " | ".join(dict.fromkeys(parts)) or "Any"
        if len(parts) > 2:
            text = "Any"
        return f"{text} | None" if "null" in shape.kinds and text != "Any" else text

    def declare(shape: Shape, origin: str, depth: int) -> str:
        signature = shape.signature()
        if signature in names:
            return names[signature]
        name = _class_name(origin)
        while name in names.values():
            name += "_"
        names[signature] = name
        lines = [f"class {name}(TypedDict):", '    __pydantic_config__ = ConfigDict(extra="allow")']
        body = []
        for key, child in sorted(shape.fields.items()):
            text = annotation(child, origin + "_" + key, depth + 1)
            if shape.present[key] < shape.objects:
                text = f"NotRequired[{text}]"
            if _IDENT.match(key):
                body.append(f"    {key}: {text}")
            else:
                body.append(f"    # field {key!r} is not an identifier: {text}")
        classes.append("\n".join(lines + (body or ["    pass"])))
        return name

    routes = []
    for (method, route), shape in sorted(shapes.items(), key=lambda item: (item[0][1], item[0][0])):
        routes.append(f"# {method} {route} -> {annotation(shape, method + ' ' + route + ' Response')}")
    header = ["from typing import Any, NotRequired", "", "from pydantic import ConfigDict", "from typing_extensions import TypedDict", "",
              "JsonSchema = dict[str, Any]", ""]
    return "\n".join(header + ["\n\n".join(classes), "", *routes]) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draft response types from recorded responses.")
    parser.add_argument("samples", type=Path)
    parser.add_argument("--emit", type=Path)
    parser.add_argument("--max-depth", type=int, default=99, help="nested objects deeper than this stay dict[str, Any]")
    args = parser.parse_args(argv)
    shapes = load(args.samples)
    found: list[tuple[str, Shape]] = []
    for (method, route), shape in shapes.items():
        walk(shape, f"{method} {route}", found)
    by_signature: dict[str, list[str]] = defaultdict(list)
    for origin, shape in found:
        by_signature[shape.signature()].append(origin)
    recurring = {sig: origins for sig, origins in by_signature.items() if len({o.split(' ', 2)[1] for o in origins}) > 1}
    print(f"routes with samples: {len(shapes)}")
    print(f"object positions: {len(found)}; distinct field sets: {len(by_signature)}; shared across routes: {len(recurring)}")
    for sig, origins in sorted(recurring.items(), key=lambda item: -len(item[1]))[:15]:
        print(f"  {len(origins):3} x [{sig[:90]}]")
    if args.emit:
        args.emit.write_text(emit(shapes, args.max_depth), encoding="utf-8")
        print(f"draft written to {args.emit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
