"""List the SiLA commands of the features a server serves, from the features themselves (so the list cannot drift
from the code): identifier, parameters with their types, and the docstring that states ranges and units."""

import inspect
import re

SKIP_PARAMETERS = {"self", "status", "intermediate", "metadata"}


def _pascal(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in name.split("_"))


def _type_name(annotation) -> str:
    if annotation is inspect.Parameter.empty:
        return ""
    if getattr(annotation, "__args__", None):  # list[str], dict[str, float] ...
        return str(annotation).replace("typing.", "")
    return getattr(annotation, "__name__", None) or str(annotation)


def _doc_parts(doc: str) -> tuple[str, dict[str, str]]:
    """The description (text before Args/Returns) and the Args entries of a Google-style docstring."""
    doc = inspect.cleandoc(doc or "")
    head = re.split(r"\n\s*(Args|Returns|Raises|Yields):", doc)[0]
    args = {}
    m = re.search(r"Args:\n(.*?)(?:\n\s*(Returns|Raises|Yields):|\Z)", doc, re.S)
    if m:
        current = None
        for line in m.group(1).splitlines():
            entry = re.match(r"\s{2}(\w+):\s*(.*)", line)
            if entry:
                current = entry.group(1)
                args[current] = entry.group(2).strip()
            elif current and line.strip():
                args[current] += " " + line.strip()
    return re.sub(r"\s+", " ", head).strip(), args


def describe(features) -> list[dict]:
    """One entry per command of the given feature instances."""
    out = []
    for feature in features:
        fqi = f"{feature.originator}/{feature.category}/{feature.identifier}/v{feature.version.split('.')[0]}"
        for name, function in inspect.getmembers(type(feature), inspect.isfunction):
            handler = getattr(function, "__handler", None)
            kind = type(handler).__name__ if handler is not None else ""
            if "Command" not in kind:
                continue
            description, args = _doc_parts(function.__doc__)
            parameters = []
            for p in inspect.signature(function).parameters.values():
                if p.name in SKIP_PARAMETERS or p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
                    continue
                identifier = _pascal(p.name)
                parameters.append({"name": identifier, "type": _type_name(p.annotation), "doc": args.get(identifier, "")})
            out.append({"feature": fqi, "command": _pascal(name), "observable": kind.startswith("Observable"),
                        "description": description, "parameters": parameters})
    return out
