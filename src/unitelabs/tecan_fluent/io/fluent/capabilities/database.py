"""Read the places, labware types, tips and liquid classes of the Fluent from the FluentControl database (read only).

The FluentControl database (``C:\\ProgramData\\Tecan\\VisionX\\DataBase``) describes the worktable as XML files:

- ``SystemSpecific\\Worktable\\Workspaces\\*.xwsp``: worktables. A worktable is a tree of components; every site of a
  component points to a site template (``BaseTemplateGuid``) and holds a component or nothing
  (``ConnectedComponent`` with ``CarrierOrLabwareTemplateGUID``).
- ``SystemSpecific\\Worktable\\Sites\\*.xsit``: site templates. ``LocationGroupName`` is the location name scripts use
  (e.g. ``Nest7mm_Pos``); ``RobotPaths`` lists the gripper paths per arm (``CGA 1`` is the RGA of this instrument).
- ``SystemSpecific\\Worktable\\Components\\*.xcmp``: component templates (labware, tips, lids, carriers, devices).
  ``FunctionalGroup`` says which (``Labware.Microplate``, ``Labware.FCA DiTi``, ``Carrier.Nest`` ...);
  ``CustomAttributes`` hold the grip widths and force, the tip capacity and whether the FCA arm may pipette on a
  carrier (``ACCESSIBLE_FOR_LIHA``); ``AllowedGripModes`` say which gripper modes a carrier allows per site.
- ``SystemSpecific\\LiquidClasses\\*.xlqc``: liquid classes, with one equation set per arm type and tip group.

What can be put where is decided by connector files, which this module does not read: a site template and a
component template list the connectors they belong to (``Reference`` with ``TypeId`` ``WorktableConnector``), and a
component fits a site when the two share one. Every placement of the OFML worktable agrees with this rule.

A place is a (location, site) of the worktable, numbered from 1 in file order per location as FluentControl's
scripts do. The FCA arm can pipette at a place when every carrier below it has ``ACCESSIBLE_FOR_LIHA`` true; the
RGA can grip there in the modes both the site template's paths and the carrier's ``AllowedGripModes`` allow. Both
are read from the definitions; FluentControl's own checks were not compared with them.
"""

import dataclasses
import html
import math
import pathlib
import re
import xml.etree.ElementTree as ET

ARM_PART = "AirFca"
"""The pipetting arm is Air FCA 1: only the AirFca part of a liquid class applies."""
GRIPPER_ARM = "CGA 1"
"""The RGA of this instrument (driver CGA:1, call name "RGA 1")."""
# Location groups that are frame parts, grids and pins rather than places for labware
STRUCTURE = ("deviceSite", "WorktablePin", "SideSegment", "BackExtension", "WorktableGrids", "Dummy", "Plexiglas",
             "SideExtension", "FrameWall", "SideFrameWall")
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


class DatabaseError(Exception):
    """The FluentControl database or the worktable cannot be read."""


def _tag(element) -> str:
    return element.tag.split("}")[-1]


def _child(element, name):
    if element is None:
        return None
    return next((c for c in element if _tag(c) == name), None)


def _children(element, name) -> list:
    return [c for c in element if _tag(c) == name] if element is not None else []


def _items(element) -> list:
    """The children of an element, or none when it is missing (an element's truth value is deprecated)."""
    return list(element) if element is not None else []


def _text(element, name, default: str = "") -> str:
    c = _child(element, name)
    return (c.text or "").strip() if c is not None and c.text else default


def _number(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _attributes(template) -> dict[str, str]:
    out = {}
    for kv in _items(_child(template, "CustomAttributes")):
        value = _child(kv, "Value")
        text = ""
        if value is not None:
            content = _child(value, "StringContent")
            text = content.text if content is not None and content.text else "".join(value.itertext())
        text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
        out[_text(kv, "Key")] = re.sub(r"\s+", " ", text).strip()
    return out


def _connectors(root) -> set[str]:
    payload = _child(root, "Payload")
    return {_text(r, "Guid") for r in _children(payload, "Reference") if _text(r, "TypeId") == "WorktableConnector"}


def _well_volume_ul(cavity) -> float | None:
    """Geometric volume of a well filled to the top, from its shapes (not the nominal volume)."""
    shapes = _child(_child(cavity, "CavityDefinition"), "ShapeList")
    volume = 0.0
    for shape in _items(shapes):
        kind = shape.get(XSI_TYPE, "").split(":")[-1]
        p = {_tag(c): _number(c.text) or 0.0 for c in shape}
        h = p.get("Height", 0.0)
        if kind == "Cylinder":
            v = math.pi * (p.get("Diameter", 0) / 2) ** 2 * h
        elif kind == "TruncatedCone":
            r1, r2 = p.get("DiameterBottom", 0) / 2, p.get("DiameterTop", 0) / 2
            v = math.pi * h / 3 * (r1 * r1 + r1 * r2 + r2 * r2)
        elif kind == "PartialSphere":
            a = p.get("Diameter", 0) / 2
            v = math.pi * h / 6 * (3 * a * a + h * h)
        elif kind in ("Cuboid", "RectangularCuboid"):
            v = (p.get("Length", 0) * p.get("Width", 0) or p.get("DimensionX", 0) * p.get("DimensionY", 0)) * h
        elif kind == "TruncatedPyramid":
            a1, a2 = p.get("AreaBottom", 0), p.get("AreaTop", 0)
            v = h / 3 * (a1 + a2 + math.sqrt(a1 * a2))
        elif kind == "Trapezoid":
            v = p.get("Length", 0) * (p.get("WidthBase", 0) + p.get("WidthTop", 0)) / 2 * h
        else:
            return None  # a volume table (UserDefined) or an unknown shape
        volume += v
    return round(volume, 1) if volume else None


def _payload(root, name: str):
    return next((e for e in root.iter() if _tag(e) == name), None)


@dataclasses.dataclass
class SiteTemplate:
    guid: str
    location: str
    gripper_paths: list[str]
    connectors: set[str]


@dataclasses.dataclass
class Component:
    guid: str
    name: str
    group: str  # FunctionalGroup, e.g. "Labware.Microplate"
    attributes: dict[str, str]
    connectors: set[str]
    height_mm: float | None = None
    grip_modes: list[dict] = dataclasses.field(default_factory=list)  # per arrangement: site index -> modes
    wells: dict | None = None
    is_lid: bool = False

    @property
    def is_labware(self) -> bool:
        return self.group.startswith("Labware.")


def read_site(path: pathlib.Path) -> SiteTemplate | None:
    root = ET.parse(path).getroot()
    t = _payload(root, "SiteTemplate")
    if t is None:
        return None
    paths = {}
    for kv in _items(_child(t, "RobotPaths")):
        paths[_text(kv, "Key")] = [_text(p, "Name") for p in _items(_child(kv, "Value"))]
    return SiteTemplate(guid=_text(t, "GUID") or path.stem, location=_text(t, "LocationGroupName"),
                        gripper_paths=[p for p in paths.get(GRIPPER_ARM, []) if p], connectors=_connectors(root))


def read_component(path: pathlib.Path) -> Component | None:
    root = ET.parse(path).getroot()
    t = _payload(root, "CarrierOrLabwareTemplate")
    name = _text(_child(root, "Payload"), "ObjectName")
    if t is None:
        return None
    comp = Component(guid=_text(t, "GUID") or path.stem, name=name, group=_text(t, "FunctionalGroup"),
                     attributes=_attributes(t), connectors=_connectors(root),
                     height_mm=_number(_text(_child(t, "Dimension"), "Z")), is_lid=_text(t, "IsLid") == "true")
    for arrangement in _items(_child(t, "Arrangements")):
        modes = {}
        for kv in _items(_child(arrangement, "AllowedGripModes")):
            per_arm = {_text(a, "Key"): [m.text for m in _items(_child(a, "Value"))] for a in _items(_child(kv, "Value"))}
            modes[int(_text(kv, "Key") or 0)] = per_arm.get(GRIPPER_ARM)
        comp.grip_modes.append(modes)
    pip = _child(t, "Pipettable")
    if pip is not None and len(pip):
        cavities = [c for c in pip.iter() if _tag(c) == "Cavity"]
        comp.wells = {"columns": int(_number(_text(pip, "XNumberOfWells")) or 0),
                      "rows": int(_number(_text(pip, "YNumberOfWells")) or 0),
                      "well_volume_ul": _well_volume_ul(cavities[0]) if cavities else None}
    return comp


@dataclasses.dataclass
class LiquidClass:
    name: str
    air_fca: bool
    tip_groups: dict[str, dict]  # tip group -> {"min_ul", "max_ul", "multi_dispense"} of the AirFca equation set


def read_liquid_class(path: pathlib.Path) -> LiquidClass | None:
    root = ET.parse(path).getroot()
    name = _text(_child(root, "Payload"), "ObjectName")
    lc = _payload(root, "LiquidClass")
    if lc is None:
        return None
    parts, groups = set(), {}
    for e in lc:
        arm = _text(_child(e, "DeviceType"), "PipettingDeviceType")
        if _tag(e).endswith("LiquidSubClass"):
            parts.add(arm)
        elif _tag(e).endswith("EquationSet") and arm == ARM_PART:
            correction = _text(e, "CorrectionVolumeFormular") + " " + _text(e, "DispenseCorrectionVolume")
            m = re.search(r"AdjustAccuracy\(\s*volume\s*,([^)]*)\)", correction)
            points = [float(x) for x in m.group(1).split(",") if x.strip()][0::2] if m else []
            groups[_text(e, "DiTiTypeGroup") or "default"] = {
                "min_ul": min(points) if points else None, "max_ul": max(points) if points else None,
                "multi_dispense": _text(e, "IsMultiPipette") == "true"}
    return LiquidClass(name=name, air_fca=ARM_PART in parts, tip_groups=groups)


def _object_name(path: pathlib.Path) -> str:
    head = path.read_bytes()[:4096].decode("utf-8", errors="replace")
    m = re.search(r"<ObjectName>([^<]*)</ObjectName>", head)
    return html.unescape(m.group(1)) if m else ""


@dataclasses.dataclass
class Place:
    location: str
    site: int
    parent: str
    parent_type: str
    labware: str | None  # label of what the worktable places here, None when empty
    labware_type: str | None
    accepts: list[str]
    gripper_modes: list[str]
    pipetting: bool | None  # None when a carrier below does not say


@dataclasses.dataclass
class Capabilities:
    database: str
    worktable: str
    places: list[Place]
    components: dict[str, Component]
    liquid_classes: list[LiquidClass]
    rga_settings: dict[str, str]

    def labware_types(self, used_only: bool = True) -> list[Component]:
        used = {name for p in self.places for name in p.accepts} | {p.labware_type for p in self.places}
        return sorted((c for c in self.components.values() if c.is_labware and (not used_only or c.name in used)),
                      key=lambda c: c.name)

    def tip_types(self) -> list[Component]:
        return [c for c in self.labware_types(used_only=False) if c.group == "Labware.FCA DiTi"]


def _walk(frame, sites: dict[str, SiteTemplate], comps: dict[str, Component], owners: dict[str, set[str]]):
    counts: dict[str, int] = {}
    places = []

    def walk(component, label, comp_guid, chain):
        for ai, arrangement in enumerate(_children(_child(component, "Arrangements"), "Arrangement")):
            for kv in _items(_child(arrangement, "Sites")):
                index = int(_text(kv, "Key") or 0)
                value = _child(kv, "Value")
                site = sites.get(_text(value, "BaseTemplateGuid"))
                location = site.location if site else ""
                counts[location] = counts.get(location, 0) + 1
                connected = _child(value, "ConnectedComponent")
                child_label, child_guid = None, None
                if connected is not None and len(connected):
                    names = [_text(x, "Value") for x in _items(_child(connected, "LabwareName"))]
                    child_label = names[0] if names else None
                    child_guid = _text(connected, "CarrierOrLabwareTemplateGUID")
                if site and location and not location.startswith(STRUCTURE) and "FrameWall" not in location:
                    accepts = sorted({comps[g].name for k in site.connectors for g in owners.get(k, ())
                                      if g in comps and comps[g].is_labware})
                    parent = comps.get(comp_guid)
                    allowed = None
                    if parent and ai < len(parent.grip_modes):
                        allowed = parent.grip_modes[ai].get(index)
                    modes = [m for m in site.gripper_paths if allowed is None or m in allowed]
                    access = [comps[g].attributes.get("ACCESSIBLE_FOR_LIHA") for g in chain if g in comps]
                    pipetting = None if any(a not in ("true", "false") for a in access) else all(a == "true" for a in access)
                    places.append(Place(location=location, site=counts[location], parent=label or "",
                                        parent_type=parent.name if parent else "", labware=child_label,
                                        labware_type=comps[child_guid].name if child_guid in comps else None,
                                        accepts=accepts, gripper_modes=modes, pipetting=pipetting))
                if child_guid:
                    walk(connected, child_label, child_guid, chain + [child_guid])

    walk(frame, "", None, [])
    return places


def load(database_root: str | pathlib.Path, worktable: str) -> Capabilities:
    """Read the database. Raises DatabaseError when the folders or the worktable are missing."""
    root = pathlib.Path(database_root)
    base = root / "SystemSpecific"
    folders = [base / "Worktable" / "Workspaces", base / "Worktable" / "Sites", base / "Worktable" / "Components"]
    if not all(f.is_dir() for f in folders):
        raise DatabaseError(f"{root} is not a FluentControl database (no SystemSpecific\\Worktable folders)")
    workspace = next((p for p in sorted(folders[0].glob("*.xwsp")) if _object_name(p) == worktable), None)
    if workspace is None:
        raise DatabaseError(f"Worktable {worktable!r} not found in {folders[0]}")
    sites = {s.guid: s for s in (read_site(p) for p in sorted(folders[1].glob("*.xsit"))) if s}
    comps = {c.guid: c for c in (read_component(p) for p in sorted(folders[2].glob("*.xcmp"))) if c}
    owners: dict[str, set[str]] = {}
    for c in comps.values():
        for k in c.connectors:
            owners.setdefault(k, set()).add(c.guid)
    frame = next((e for e in ET.parse(workspace).getroot().iter() if _tag(e) == "Frame"), None)
    if frame is None:
        raise DatabaseError(f"Worktable {worktable!r} has no frame")
    places = _walk(frame, sites, comps, owners)
    classes = [lc for lc in (read_liquid_class(p) for p in sorted((base / "LiquidClasses").glob("*.xlqc"))) if lc]
    rga = {}
    for p in sorted((base / "DriverConfiguration").glob("*.xdrv")):
        if _object_name(p) == "RGA 1":
            text = p.read_text(encoding="utf-8", errors="replace")
            for key in ("GripDetection", "RegripStation", "Force", "ZeroForce", "Speed"):
                m = re.search(rf"<{key}>([^<]*)</{key}>", text)
                if m:
                    rga[key] = m.group(1)
    return Capabilities(database=str(root), worktable=worktable, places=places, components=comps,
                        liquid_classes=sorted(classes, key=lambda c: c.name), rga_settings=rga)
