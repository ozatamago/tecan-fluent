"""RGA clearance check: would any part of the RGA (or the labware it carries) hit something while it goes straight down
to the grip height at the source or the destination of a transfer, or back up to the safe height?

Why: FluentControl's path planner plans and checks the RGA's travel at safe height only. The final descents to the
grip and place positions are taught "stored moves" that it executes without any collision check, and its simulation
does not catch them either. On 2026-11-18 the RGA hit a 1000 ul tip rack this way: gripping in the left column of
7 mm nests (C=180), the RGA body sits 152.5 mm to +X, over the right column, and the gripper blocks reach 68.9 mm to
either side in Y, i.e. over the neighbouring rows.

What is checked (pure geometry, no FluentControl needed): the RGA parts (fingers, gripper assembly blocks, rotator,
pillar) as boxes around the TCP, from FluentControl's own RGA collision model, and the carried labware, swept
vertically from the grip height to the safe height at both ends of the transfer, against the fixed objects of the deck
and every modelled labware on it (the moved labware itself, what it stands on and its own nest are left out). The
data (site positions, grip heights, object heights, parts) is in data/fluent780_rga_geometry.json, each value marked
measured, estimated or assumed.

Not checked: the horizontal travel at safe height (left to FluentControl's path planner) and the interiors of the
hotel, the incubator and the reader (not modelled; those moves were validated on the instrument).

A transfer whose labware type, source, destination or grip height is not in the table cannot be checked; the caller
decides whether that refuses the move (the default) or only warns.
"""

from __future__ import annotations

import copy
import dataclasses
import html
import json
import math
import pathlib
import re

from unitelabs.cdk.config import Config

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
GEOMETRY_FILE = DATA / "fluent780_rga_geometry.json"
UNKNOWN_POLICIES = ("refuse", "warn")


@dataclasses.dataclass
class RgaClearanceConfig(Config):
    """The RGA clearance check before every RGA transfer (io/fluent/rga_clearance.py)."""

    enabled: bool = True
    """Check every RGA transfer against the deck before it is sent (False: no check at all)."""
    margin_mm: float = 2.5
    """A transfer is refused when any RGA part or the carried labware comes closer than this to anything (mm). The
    closest move that passed on the instrument had 3.0 mm in the model (2026-11-18 13:08)."""
    unknown: str = "refuse"
    """What to do with a transfer that cannot be checked (labware type, site or grip height not in the table, or the
    deck could not be read): "refuse" (default; an unchecked descent is what hit the tip rack on 2026-11-18) or "warn"
    (send it anyway; the record and the log say it was not checked)."""
    geometry_file: str = ""
    """JSON file with the geometry (empty: the table that comes with the connector,
    data/fluent780_rga_geometry.json)."""


# ---------------------------------------------------------------- geometry
@dataclasses.dataclass(frozen=True)
class Box:
    """Axis-aligned box in deck coordinates (mm). unknown: something of unknown height stands there."""

    x0: float
    x1: float
    y0: float
    y1: float
    z0: float
    z1: float
    name: str
    unknown: bool = False

    def overlaps_in_plan(self, other: Box) -> bool:
        return max(self.x0 - other.x1, other.x0 - self.x1) <= 0 and max(self.y0 - other.y1, other.y0 - self.y1) <= 0


@dataclasses.dataclass(frozen=True)
class Site:
    location: str
    site: int
    x: float | None
    y: float | None
    cls: str
    modelled: bool
    surface_z: float
    grip_mode: str = ""
    own_fixed: tuple = ()
    """Fixed objects that belong to the site itself (its nest, the device it is on): left out at this site."""

    @property
    def name(self) -> str:
        return f"{self.location}[{self.site}]"


class Geometry:
    """The table of data/fluent780_rga_geometry.json."""

    def __init__(self, data: dict):
        self.data = data
        self.worktables = list(data.get("worktables") or [])
        """The worktables the table describes (empty: any)."""
        self.safe_z = float(data["safe_z"])
        self.axis = float(data["rga"]["axis_distance"])
        self.parts = data["rga"]["parts"]
        self.pillar = data["rga"]["pillar"]
        self.modes = data["grip_modes"]
        self.classes = data["site_classes"]
        self.kinds = data["kinds"]
        self.rules = [r for r in data["kind_rules"] if "kind" in r]
        self.footprint = data["footprint"]
        self.grips = data["grips"]
        self.exceptions = data.get("exceptions", [])

    @classmethod
    def load(cls, path: str | pathlib.Path = "") -> Geometry:
        p = pathlib.Path(path).expanduser() if path else GEOMETRY_FILE
        return cls(json.loads(p.read_text(encoding="utf-8")))

    def site(self, location: str, site: int) -> Site | None:
        sites = self.data["sites"].get(location)
        if not isinstance(sites, dict):
            return None
        s = sites.get(str(int(site))) or sites.get("*")
        if s is None:
            return None
        c = self.classes[s["class"]]
        own = [*c.get("own_fixed", []), *s.get("own_fixed", [])]
        nest_of = s.get("same_as") or f"{location}[{int(site)}]"  # a second location group on the same place
        if c.get("nest"):
            own.append(nest_name(c["nest"], nest_of))
        return Site(
            location,
            int(site),
            s.get("x"),
            s.get("y"),
            s["class"],
            bool(c.get("modelled", True)),
            float(c.get("surface_z", 0.0)),
            c.get("grip_mode", ""),
            tuple(own),
        )

    def exceptions_for(self, site: Site, mode: str, kind: str) -> list[dict]:
        """The documented exceptions (part / obstacle pairs not counted) for a grip at this site."""
        return [
            e
            for e in self.exceptions
            if e["site"] == site.name
            and e["mode"] == mode
            and kind in e["kinds"]
            and e.get("part")
            and e.get("obstacle")
        ]

    def kind_of(self, label: str, labware_type: str) -> str | None:
        for rule in self.rules:
            if "label" in rule and re.search(rule["label"], label or ""):
                return rule["kind"]
            if "type" in rule and re.search(rule["type"], labware_type or ""):
                return rule["kind"]
        return None

    def grip(self, kind: str, cls: str, on_kind: str | None, mode: str) -> dict | None:
        for g in self.grips:
            if (g["kind"], g["class"], g.get("on"), g.get("mode", "NARROW")) == (kind, cls, on_kind, mode):
                return g
        return None

    def fixed(self) -> list[Box]:
        """The fixed objects, and the nests of the sites that have one."""
        out = [
            Box(*f["x"], *f["y"], *f["z"], f["name"], bool(f.get("unknown"))) for f in self.data["fixed"] if "name" in f
        ]
        for location, sites in self.data["sites"].items():
            if not isinstance(sites, dict):
                continue
            for number, s in sites.items():
                nest = self.classes[s["class"]].get("nest")
                if nest and number != "*" and not s.get("same_as"):
                    x, y = s["x"], s["y"]
                    hx, hy = nest["half_x"], nest["half_y"]
                    name = nest_name(nest, f"{location}[{int(number)}]")
                    out.append(Box(x - hx, x + hx, y - hy, y + hy, 0.0, nest["top"], name))
        return out


def nest_name(nest: dict, site: str) -> str:
    return f"{nest.get('name', 'nest')} {site}"


def rga_boxes(geo: Geometry, x: float, y: float, c: float, g: float) -> list[Box]:
    """The RGA parts with the TCP at (x, y, 0), rotation C (degrees) and gripper width G (z relative to the TCP)."""
    ux, uy = -math.cos(math.radians(c)), -math.sin(math.radians(c))  # TCP -> rotation axis
    vx, vy = -uy, ux
    out = []
    for p in geo.parts:
        centres = (g / 2, -g / 2) if p["per_finger"] else (0.0,)
        for centre in centres:
            corners = [(x + a * ux + (centre + b) * vx, y + a * uy + (centre + b) * vy) for a in p["u"] for b in p["v"]]
            xs, ys = [q[0] for q in corners], [q[1] for q in corners]
            out.append(Box(min(xs), max(xs), min(ys), max(ys), p["z"][0], p["z"][1], p["name"]))
    ax, ay = x + geo.axis * ux, y + geo.axis * uy
    pl = geo.pillar
    out.append(Box(ax + pl["x"][0], ax + pl["x"][1], ay + pl["y"][0], ay + pl["y"][1], *pl["z"], pl["name"]))
    return out


def carried_box(geo: Geometry, x: float, y: float, carry: dict, name: str) -> Box:
    """The carried labware (its SBS footprint, as it stands on the deck) with the TCP at (x, y, 0)."""
    hx, hy = geo.footprint["half_x"], geo.footprint["half_y"]
    return Box(x - hx, x + hx, y - hy, y + hy, -carry["below"], carry["above"], f"carried {name}")


def sweep_gap(part: Box, z0: float, z1: float, obstacle: Box) -> tuple[float, float] | None:
    """Smallest vertical gap between a part (z relative to the TCP) and an obstacle while the TCP goes from z0 to z1,
    and the TCP height where it occurs. Negative: they overlap by that much. None: they never meet in plan view."""
    if not part.overlaps_in_plan(obstacle):
        return None
    # gap(z) = max(z + part.z0 - obstacle.z1, obstacle.z0 - z - part.z1) is smallest where both terms are equal
    lo, hi = min(z0, z1), max(z0, z1)
    z = min(max((obstacle.z0 + obstacle.z1 - part.z0 - part.z1) / 2, lo), hi)
    return max(z + part.z0 - obstacle.z1, obstacle.z0 - z - part.z1), z


@dataclasses.dataclass
class Worst:
    gap: float | None = None
    """Smallest gap (mm), None when nothing is within reach."""
    part: str = ""
    obstacle: str = ""
    tcp_z: float | None = None
    unknown: list = dataclasses.field(default_factory=list)
    """Names of obstacles of unknown height that a part passes over."""
    excepted: list = dataclasses.field(default_factory=list)
    """Documented exceptions that applied: {"part", "obstacle", "gap_mm", "reason"}."""

    def take(self, gap: float, part: str, obstacle: str, z: float) -> None:
        if self.gap is None or gap < self.gap:
            self.gap, self.part, self.obstacle, self.tcp_z = gap, part, obstacle, z


def vertical_check(
    geo: Geometry,
    x: float,
    y: float,
    z0: float,
    z1: float,
    c: float,
    g: float,
    carry: dict | None,
    obstacles: list[Box],
    exclude: set = frozenset(),
    carry_name: str = "labware",
    exceptions: list = (),
) -> Worst:
    """The smallest gap while the TCP goes straight from z0 to z1 at (x, y) with rotation c and gripper width g.
    exceptions: documented part / obstacle pairs ({"part", "obstacle", "reason"}) that are not counted (and are
    reported in Worst.excepted)."""
    excepted = {(e["part"], e["obstacle"]): e for e in exceptions}
    parts = rga_boxes(geo, x, y, c, g)
    if carry is not None:
        parts.append(carried_box(geo, x, y, carry, carry_name))
    worst = Worst()
    for ob in obstacles:
        if ob.name in exclude:
            continue
        for part in parts:
            hit = sweep_gap(part, z0, z1, ob)
            if hit is None:
                continue
            if ob.unknown:
                if ob.name not in worst.unknown:
                    worst.unknown.append(ob.name)
                continue
            e = excepted.get((part.name, ob.name))
            if e is not None:
                if not any((x["part"], x["obstacle"]) == (part.name, ob.name) for x in worst.excepted):
                    worst.excepted.append(
                        {"part": part.name, "obstacle": ob.name, "gap_mm": round(hit[0], 1), "reason": e["reason"]}
                    )
                continue
            worst.take(hit[0], part.name, ob.name, hit[1])
    return worst


# ---------------------------------------------------------------- what is on the deck
@dataclasses.dataclass
class Item:
    """A labware on the deck: FluentControl's location and site, and what it stands on (on: the label of the labware
    under it, e.g. the plate under a lid at a cover site)."""

    type: str
    location: str
    site: int
    on: str = ""
    lid: bool = False
    """A lid is recorded for it in the deck state (Deck.PlaceLabware with Lid)."""


@dataclasses.dataclass
class Snapshot:
    items: dict
    """label -> Item: everything on the deck."""
    base: dict
    """label -> Item: the base positions (for a move to the base position)."""
    notes: list = dataclasses.field(default_factory=list)

    def copy(self) -> Snapshot:
        return Snapshot(copy.deepcopy(self.items), self.base, list(self.notes))


def cover_parent(location: str) -> str:
    """The plate whose cover site a location expression names (GetCoverSiteName("plate") -> "plate"), else ""."""
    m = re.fullmatch(r'GetCoverSiteName\("(.+)"\)', location or "")
    return m.group(1) if m else ""


def snapshot(base_labware: dict, deck_entries: dict | None = None, overlay: dict | None = None) -> Snapshot:
    """What is on the deck: the labware of the base worktable (label -> {"type", "location", "site", "on"}), changed by
    the deck state's entries (io/fluent/deck/state.py) and then by the moves of the open run (overlay: label -> Item,
    or None for labware removed in the run)."""
    base = {
        label: Item(b.get("type", ""), b["location"], int(b["site"]), b.get("on", "") or "")
        for label, b in base_labware.items()
        if b.get("location")
    }
    items = copy.deepcopy(base)
    for label, e in (deck_entries or {}).items():
        if e.get("location") is None:
            items.pop(label, None)
            continue
        b = base.get(label)
        at_base = b is not None and (b.location, b.site) == (e["location"], int(e["site"]))
        items[label] = Item(
            e.get("type") or (b.type if b else ""),
            e["location"],
            int(e["site"]),
            b.on if at_base else cover_parent(e["location"]),  # a lid the deck state keeps on a plate's cover site
            bool(e.get("lid")),
        )
        if label not in base and e.get("base"):
            base[label] = Item(items[label].type, e["base"]["location"], int(e["base"]["site"]))
    for label, item in (overlay or {}).items():
        if item is None:
            items.pop(label, None)
        else:
            items[label] = copy.deepcopy(item)
    return Snapshot(items, base)


def resolve(geo: Geometry, snap: Snapshot, label: str, depth: int = 0) -> tuple[Site | None, list[str]]:
    """The site a labware physically stands at, and the labels under it (a lid on a plate: [plate])."""
    item = snap.items.get(label)
    if item is None:
        return None, []
    site = geo.site(item.location, item.site)
    if site is not None:
        return site, []
    if item.on and depth < 4:
        site, below = resolve(geo, snap, item.on, depth + 1)
        if site is not None:
            return site, [item.on, *below]
    return None, []


def _position(item: Item) -> str:
    return f"{item.location}[{item.site}]" if item.site else item.location


def obstacles(geo: Geometry, snap: Snapshot) -> tuple[list[Box], list[str]]:
    """Boxes of the fixed objects and of every modelled labware on the deck, and the labware that is not modelled
    (standing outside the sites of the table)."""
    boxes = geo.fixed()
    lidded = {item.on for item in snap.items.values() if item.on}
    not_modelled = []
    hx, hy = geo.footprint["half_x"], geo.footprint["half_y"]
    for label, item in sorted(snap.items.items()):
        site, below = resolve(geo, snap, label)
        if site is None:
            not_modelled.append(f"{label} at {_position(item)}")
            continue
        if below or not site.modelled:
            continue  # a lid is part of the height of what it stands on; nothing inside the hotel etc. is modelled
        x, y = site.x, site.y
        kind = geo.kind_of(label, item.type)
        name = f"{label} at {site.name}"
        if kind is None:
            boxes.append(Box(x - hx, x + hx, y - hy, y + hy, site.surface_z, site.surface_z, name, True))
            continue
        k = geo.kinds[kind]
        with_lid = label in lidded or item.lid
        height = k.get("height_with_lid", k["height"]) if with_lid else k["height"]
        boxes.append(Box(x - hx, x + hx, y - hy, y + hy, site.surface_z, site.surface_z + height, name))
    return boxes, not_modelled


# ---------------------------------------------------------------- one transfer
@dataclasses.dataclass
class End:
    """The vertical moves at one end of a transfer."""

    where: str
    """"source" or "destination"."""
    site: str
    modelled: bool = True
    grip_z: float | None = None
    grip_status: str = ""
    worst: Worst = dataclasses.field(default_factory=Worst)

    def as_dict(self) -> dict:
        out = {"where": self.where, "site": self.site, "modelled": self.modelled}
        if self.modelled:
            out.update(
                grip_z=self.grip_z,
                grip_status=self.grip_status,
                gap_mm=None if self.worst.gap is None else round(self.worst.gap, 1),
                part=self.worst.part,
                obstacle=self.worst.obstacle,
                tcp_z=None if self.worst.tcp_z is None else round(self.worst.tcp_z, 1),
            )
            if self.worst.unknown:
                out["unknown_obstacles"] = self.worst.unknown
            if self.worst.excepted:
                out["exceptions_applied"] = self.worst.excepted
        return out


@dataclasses.dataclass
class Result:
    labware: str
    source: str
    destination: str
    mode: str = ""
    ends: list = dataclasses.field(default_factory=list)
    collisions: list = dataclasses.field(default_factory=list)
    """Why the transfer is refused: a part comes closer than the margin to something."""
    unknown: list = dataclasses.field(default_factory=list)
    """Why the transfer could not be checked (unknown labware type, site, grip height or obstacle)."""
    notes: list = dataclasses.field(default_factory=list)

    @property
    def verdict(self) -> str:
        return "collision" if self.collisions else "unknown" if self.unknown else "ok"

    @property
    def worst(self) -> End | None:
        ends = [e for e in self.ends if e.modelled and e.worst.gap is not None]
        return min(ends, key=lambda e: e.worst.gap) if ends else None

    def as_dict(self) -> dict:
        out = {
            "labware": self.labware,
            "source": self.source,
            "destination": self.destination,
            "mode": self.mode,
            "verdict": self.verdict,
            "ends": [e.as_dict() for e in self.ends],
        }
        for key in ("collisions", "unknown", "notes"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        return out

    def summary(self) -> str:
        head = f"{self.labware}: {self.source} -> {self.destination}"
        if self.collisions:
            return f"{head}: REFUSED: " + " / ".join(self.collisions)
        if self.unknown:
            return f"{head}: NOT CHECKED: " + " / ".join(self.unknown)
        w = self.worst
        if w is None:
            gap = "nothing within reach of the vertical moves"
        else:
            gap = (
                f"smallest gap {w.worst.gap:.1f} mm ({w.worst.part} - {w.worst.obstacle}, at the {w.where} "
                f"{w.site}, TCP Z {w.worst.tcp_z:.1f})"
            )
        skipped = [f"{e.where} {e.site}" for e in self.ends if not e.modelled]
        tail = f"; not modelled: {', '.join(skipped)}" if skipped else ""
        return f"{head}: OK, {gap}{tail}"


@dataclasses.dataclass
class Destination:
    """Where a transfer goes: a site, the base position of the labware, or onto a plate (its cover site)."""

    location: str = ""
    site: int = 0
    base: bool = False
    onto: str = ""

    def text(self) -> str:
        if self.base:
            return "base"
        if self.onto:
            return f"lid of {self.onto}"
        return f"{self.location}[{self.site}]"


def _moved(snap: Snapshot, label: str, dest: Destination) -> Item | None:
    """The labware's entry after the transfer (None: the destination is not known)."""
    item = snap.items[label]
    if dest.base:
        b = snap.base.get(label)
        return None if b is None else Item(item.type, b.location, b.site, b.on, item.lid)
    if dest.onto:
        b = snap.base.get(label)
        if b is not None and b.on == dest.onto:
            return Item(item.type, b.location, b.site, b.on)
        return Item(item.type, f'GetCoverSiteName("{dest.onto}")', 0, dest.onto)
    return Item(item.type, dest.location, int(dest.site), "", item.lid)


def _gap_text(gap: float) -> str:
    return f"{-gap:.1f} mm into it" if gap < 0 else f"within {gap:.1f} mm of it"


def check_transfer(geo: Geometry, snap: Snapshot, label: str, dest: Destination, margin: float) -> Result:
    """Check one RGA transfer against the deck. Does not change snap."""
    item = snap.items.get(label)
    result = Result(label, _position(item) if item else "?", dest.text())
    if item is None:
        result.unknown.append(f"{label} is not on the deck (neither on the base worktable nor in the deck state)")
        return result
    kind = geo.kind_of(label, item.type)
    if kind is None:
        result.unknown.append(f"labware type '{item.type}' of {label} is not in the RGA geometry table")
    src, src_below = resolve(geo, snap, label)
    if src is None:
        result.unknown.append(f"the source {_position(item)} of {label} is not in the RGA geometry table")
    after = snap.copy()
    new = _moved(snap, label, dest)
    if new is None:
        result.unknown.append(f"the base position of {label} is not known")
        return result
    after.items[label] = new
    dst, dst_below = resolve(geo, after, label)
    if dst is None:
        result.unknown.append(f"the destination {dest.text()} of {label} is not in the RGA geometry table")
    if dst is not None and dest.onto:
        result.destination = f"lid of {dest.onto} at {dst.name}"
    if src is not None and src_below:
        result.source = f"{_position(item)} (on {src_below[0]} at {src.name})"
    if kind is None or src is None or dst is None:
        return result
    mode = "WIDE" if "WIDE" in (src.grip_mode, dst.grip_mode) else "NARROW"
    result.mode = mode
    with_lid = item.lid or any(i.on == label for i in snap.items.values())
    k = geo.kinds[kind]
    carry = (k.get("carry_with_lid") if with_lid else None) or k.get("carry")
    for where, site, below, state in (("source", src, src_below, snap), ("destination", dst, dst_below, after)):
        end = End(where, site.name, site.modelled)
        result.ends.append(end)
        if not site.modelled:
            continue
        on_kind = geo.kind_of(below[0], state.items[below[0]].type) if below else None
        grip = geo.grip(kind, site.cls, on_kind, mode)
        if grip is None:
            what = f"on a {on_kind} " if on_kind else ""
            result.unknown.append(
                f"no {mode} grip height for a {kind} {what}at a {site.cls} site ({where} {site.name}) in the RGA "
                "geometry table"
            )
            continue
        if carry is None:
            result.unknown.append(f"the size of a carried {kind} is not in the RGA geometry table")
            continue
        end.grip_z, end.grip_status = float(grip["z"]), grip.get("status", "")
        boxes, _ = obstacles(geo, state)
        exclude = {f"{lab} at {site.name}" for lab in [label, *below]} | set(site.own_fixed)
        allowed = geo.exceptions_for(site, mode, kind)
        c, g_open = geo.modes[mode]["C"], geo.modes[mode]["G_open"]
        # empty fingers (open) on the way down at the source and up at the destination; holding the labware the other
        # way; both are checked at both ends
        for g, load in ((g_open, None), (float(grip["G"]), carry)):
            w = vertical_check(geo, site.x, site.y, end.grip_z, geo.safe_z, c, g, load, boxes, exclude, label, allowed)
            if w.gap is not None:
                end.worst.take(w.gap, w.part, w.obstacle, w.tcp_z)
            end.worst.unknown += [u for u in w.unknown if u not in end.worst.unknown]
            for x in w.excepted:
                if not any((y["part"], y["obstacle"]) == (x["part"], x["obstacle"]) for y in end.worst.excepted):
                    end.worst.excepted.append(x)
        for x in end.worst.excepted:
            result.notes.append(
                f"exception applied at the {where} {site.name}: {x['part']} - {x['obstacle']} "
                f"({x['gap_mm']:g} mm in the model) not counted: {x['reason']}"
            )
        if end.worst.gap is not None and end.worst.gap < margin:
            result.collisions.append(
                f"at the {where} {site.name} the RGA's {end.worst.part} would come {_gap_text(end.worst.gap)}: "
                f"{end.worst.obstacle} (TCP Z {end.worst.tcp_z:.1f}, grip Z {end.grip_z:.1f} ({end.grip_status}), "
                f"margin {margin:g} mm)"
            )
        for u in end.worst.unknown:
            result.unknown.append(f"at the {where} {site.name} the RGA passes over {u}, whose height is not known")
    return result


# ---------------------------------------------------------------- sequences of statements and of planned moves
def _unescape(xml: str) -> str:
    for _ in range(4):
        new = html.unescape(xml)
        if new == xml:
            break
        xml = new
    return xml


RGA_MACRO = "RGA1_TransferLabware"


def rga_transfer(xml: str) -> tuple[str, Destination] | None:
    """The labware and destination of an RGA1_TransferLabware statement (None for any other statement)."""
    if RGA_MACRO not in xml:
        return None
    t = _unescape(xml)

    def field(tag: str) -> str:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", t, re.S)
        return m.group(1).strip() if m else ""

    labware, location, site = field("Labware"), field("Location"), field("Site")
    if field("MoveToBase").lower() == "true":
        return labware, Destination(base=True)
    m = re.fullmatch(r'GetCoverSiteName\("(.+)"\)', location)
    if m:
        return labware, Destination(onto=m.group(1))
    return labware, Destination(location, int(site) if site.isdigit() else 0)


def _labware_statement(xml: str) -> tuple[str, Item | None] | None:
    """(label, Item) of an AddLabware statement, (label, None) of a RemoveLabware statement, else None."""
    if "AddLabwareDataV1" in xml:
        t = _unescape(xml)
        label = re.search(r"<LabwareLable>([^<]*)</LabwareLable>", t)
        if label:
            ltype = re.search(r"<LabwareType>([^<]*)</LabwareType>", t)
            loc = re.search(r"<Location>([^<]*)</Location>", t)
            pos = re.search(r"<Position>(\d+)</Position>", t)
            location = loc.group(1).strip() if loc else ""
            # A lid added at the cover site of a plate (Location GetCoverSiteName("plate")) stands on that plate,
            # as after an RGA transfer onto it (Destination.onto)
            return label.group(1).strip(), Item(
                ltype.group(1).strip() if ltype else "",
                location,
                int(pos.group(1)) if pos else 0,
                cover_parent(location),
            )
    if "RemoveLabwareDataV1" in xml:
        m = re.search(r"<LabwareName>([^<]*)</LabwareName>", _unescape(xml))
        if m:
            return m.group(1).strip(), None
    return None


def apply_statement(snap: Snapshot, xml: str) -> None:
    """Change snap as FluentControl would after the statement (AddLabware, RemoveLabware, an RGA transfer)."""
    stmt = _labware_statement(xml)
    if stmt is not None:
        label, item = stmt
        if item is None:
            snap.items.pop(label, None)
        else:
            snap.items[label] = item
        return
    move = rga_transfer(xml)
    if move is not None and move[0] in snap.items:
        new = _moved(snap, move[0], move[1])
        if new is not None:
            snap.items[move[0]] = new


def check_steps(geo: Geometry, snap: Snapshot, steps: list[tuple[str, str]], margin: float) -> list[Result]:
    """Check every RGA transfer of a list of statements in order, each against the deck as the statements before it
    leave it. Does not change snap."""
    snap = snap.copy()
    results = []
    for _, xml in steps:
        move = rga_transfer(xml)
        if move is not None:
            results.append(check_transfer(geo, snap, move[0], move[1], margin))
        apply_statement(snap, xml)
    return results


MOVE = re.compile(r"^\s*(?P<label>.+?\])\s*(?:\((?P<type>[^()]*)\))?\s*(?::\s*(?P<src>.*?))?\s*->\s*(?P<dst>.+?)\s*$")
POSITION = re.compile(r"^(?P<loc>[^\[\]]+)\[(?P<site>\d+)\]$")


def parse_destination(text: str) -> Destination:
    text = text.strip()
    if text.lower() == "base":
        return Destination(base=True)
    m = re.fullmatch(r"(?:lid of|onto)\s+(.+)", text, re.I)
    if m:
        return Destination(onto=m.group(1).strip())
    m = POSITION.fullmatch(text)
    if not m:
        raise ValueError(f"'{text}' is not a position like Nest7mm_Pos[2], 'base' or 'lid of <plate>'")
    return Destination(m.group("loc").strip(), int(m.group("site")))


def check_moves(geo: Geometry, snap: Snapshot, moves: list[str], margin: float) -> list[Result]:
    """Check a planned sequence of RGA transfers, each line "label: source -> destination" (or "label -> destination"
    from where it is now; "label (type): source -> destination" for labware that is not on the deck). Source and
    destination are positions like Nest7mm_Pos[2]; the destination can also be "base" or "lid of <plate>". Each move is
    applied to a copy of the deck before the next one is checked. A source that differs from the deck is taken as
    given (and noted)."""
    snap = snap.copy()
    results = []
    for line in moves:
        m = MOVE.match(line or "")
        if not m:
            r = Result(line, "?", "?")
            r.unknown.append("not a move of the form 'label: source -> destination'")
            results.append(r)
            continue
        label = m.group("label").strip()
        try:
            dest = parse_destination(m.group("dst"))
            src = m.group("src")
            notes = []
            if src and src.strip():
                pos = parse_destination(src)
                if pos.base or pos.onto:
                    raise ValueError("the source must be a position like Nest7mm_Pos[2]")
                item = snap.items.get(label)
                if item is None:
                    item = Item((m.group("type") or "").strip(), pos.location, pos.site)
                    notes.append(f"{label} is not on the deck; taken as standing at {pos.text()}")
                elif (item.location, item.site) != (pos.location, pos.site):
                    notes.append(f"the deck has {label} at {_position(item)}; taken as standing at {pos.text()}")
                    item = Item(item.type, pos.location, pos.site, "", item.lid)
                snap.items[label] = item
        except ValueError as exc:
            r = Result(label, m.group("src") or "?", m.group("dst"))
            r.unknown.append(str(exc))
            results.append(r)
            continue
        r = check_transfer(geo, snap, label, dest, margin)
        r.notes += notes
        results.append(r)
        if label in snap.items:
            new = _moved(snap, label, dest)
            if new is not None:
                snap.items[label] = new
    return results


def main(argv: list[str] | None = None) -> int:
    """Check planned moves offline, without the Fluent PC:

    python -m unitelabs.tecan_fluent.io.fluent.rga_clearance LAYOUT.json MOVES.txt [--margin 5] [--geometry FILE]

    LAYOUT.json: what is on the deck, {"label": {"type": ..., "location": ..., "site": n, "on": "label under it"}}.
    MOVES.txt: one move per line as for Deck.CheckRgaMoves. Exit status 1 when a move is refused or not checked."""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__.splitlines()[0])
    parser.add_argument("layout")
    parser.add_argument("moves")
    parser.add_argument("--margin", type=float, default=RgaClearanceConfig.margin_mm)
    parser.add_argument("--geometry", default="")
    args = parser.parse_args(argv)
    layout = json.loads(pathlib.Path(args.layout).read_text(encoding="utf-8"))
    moves = [ln for ln in pathlib.Path(args.moves).read_text(encoding="utf-8").splitlines() if ln.strip()]
    results = check_moves(Geometry.load(args.geometry), snapshot(layout), moves, args.margin)
    for i, r in enumerate(results, 1):
        print(f"{i}. {r.summary()}" + (f" (note: {'; '.join(r.notes)})" if r.notes else ""))
    return 0 if all(r.verdict == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
