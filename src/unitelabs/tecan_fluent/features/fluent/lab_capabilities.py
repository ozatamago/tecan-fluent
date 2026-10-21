"""Read-only feature that describes what the Fluent can hold and do, for planning across a lab
(docs/lab_capabilities_spec.md). Nothing here moves the instrument or changes FluentControl."""

import asyncio
import dataclasses
import json
import time

from unitelabs.cdk import sila
from unitelabs.cdk.config import Config

from ...io.fluent.capabilities import catalog, commands, database
from ...io.fluent.deck.state import DeckState
from ...io.fluentcontrol.backend import FluentControlBackend
from ...io.fluentcontrol.definitions import REMOTE_DB

SCHEMA = "riken-fluent-capabilities/1"


@dataclasses.dataclass
class CapabilitiesConfig(Config):
    """Where the description of the Fluent is read from."""

    database_root: str = REMOTE_DB
    """The FluentControl database. Read directly, so the server has to run on the Fluent PC."""
    worktable: str = ""
    """Worktable to describe. Empty: the worktable of the definition checks (fluent.definitions.workspace)."""
    cache_s: float = 600.0
    """Read the database again at most this often (seconds); reading takes a few seconds."""


class DatabaseUnavailable(Exception):
    """The FluentControl database could not be read (the server does not run on the Fluent PC, or the worktable is
    missing). The description says why."""


@dataclasses.dataclass
class PlaceInfo(sila.CustomDataType):
    """
    One place of the worktable: a site of a location, as FluentControl's scripts address it.

    Args:
      Location: Location name used in scripts, e.g. "Nest7mm_Pos".
      Site: Site number within the location, from 1.
      Carrier: Label of the carrier the site belongs to, e.g. "7mm Nest_Custom[004]".
      Labware: Label of the labware the worktable puts there ("type label"), empty when the place is empty.
      Accepts: Labware types that fit the place (they share a connector with its site template).
      GripperModes: Modes the RGA may use there: Narrow, NarrowReverse, Wide, WideReverse. Empty: no gripper access.
      Pipetting: "yes" when every carrier below allows the FCA arm, "no" when one does not, "unknown" otherwise.
    """

    location: str
    site: int
    carrier: str
    labware: str
    accepts: list[str]
    gripper_modes: list[str]
    pipetting: str


@dataclasses.dataclass
class LabwareTypeInfo(sila.CustomDataType):
    """
    One labware type defined in FluentControl that fits some place of the worktable.

    Args:
      Name: Labware type name, e.g. "96 Well Skirted PCR_Custom".
      Kind: FluentControl's functional group without "Labware.", e.g. "Microplate", "Deep Well", "Lid", "FCA DiTi".
      Columns: Number of well columns (0 for labware without wells).
      Rows: Number of well rows.
      HeightMm: Height in mm.
      WellVolumeUl: Geometric volume of one well filled to the top, in uL (0 when unknown); not a nominal volume.
      GripNarrowMm: Grip width of the RGA in Narrow mode, mm (0 when not defined).
      GripWideMm: Grip width in Wide mode, mm.
      GripForce: Grip force setting.
    """

    name: str
    kind: str
    columns: int
    rows: int
    height_mm: float
    well_volume_ul: float
    grip_narrow_mm: float
    grip_wide_mm: float
    grip_force: float


@dataclasses.dataclass
class TipTypeInfo(sila.CustomDataType):
    """
    One FCA tip type.

    Args:
      Name: Tip type, e.g. "FCA, 200ul SBS".
      TipGroup: Tip group the liquid classes use for it, e.g. "FCA DiTi 200µl".
      CapacityUl: TipCapacity of the definition, in uL (larger than the nominal volume).
      Filtered: True for filter tips.
      Racks: Labels of the racks of this type on the worktable, as "label at location[site]".
    """

    name: str
    tip_group: str
    capacity_ul: float
    filtered: bool
    racks: list[str]


@dataclasses.dataclass
class LiquidClassInfo(sila.CustomDataType):
    """
    One liquid class.

    Args:
      Name: Liquid class name, e.g. "Water Free Single".
      AirFca: True when it has an AirFca part, the only part this instrument uses.
      TipGroups: For each tip group the AirFca part has equations for, "<group>: <min>-<max> uL" (the points of its
        accuracy correction) with " multi" when it is set up to dispense several times.
    """

    name: str
    air_fca: bool
    tip_groups: list[str]


@dataclasses.dataclass
class InstrumentInfo(sila.CustomDataType):
    """
    One instrument of the deck.

    Args:
      Name: Instrument, e.g. "Inheco ODTC 96".
      Kind: What it is, e.g. "thermal cycler".
      OnWorktable: True when its component is on the worktable.
      Locations: Location names of its places.
      Driver: Driver FluentControl uses. Empty for passive parts.
      Connection: How it is connected, as far as known.
      Servers: SiLA servers of this connector that drive it ("name :port").
      Features: SiLA features that drive it.
    """

    name: str
    kind: str
    on_worktable: bool
    locations: list[str]
    driver: str
    connection: str
    servers: list[str]
    features: list[str]


@dataclasses.dataclass
class CommandInfo(sila.CustomDataType):
    """
    One SiLA command this server offers.

    Args:
      Feature: Fully qualified feature identifier.
      Command: Command identifier.
      Parameters: "<name> (<type>): <description>" per parameter; descriptions give ranges and units.
      Description: What the command does.
    """

    feature: str
    command: str
    parameters: list[str]
    description: str


@dataclasses.dataclass
class ConstraintInfo(sila.CustomDataType):
    """
    One rule a plan for the Fluent must follow.

    Args:
      Id: Short identifier, e.g. "one-aspirate-per-tip".
      Category: "pipetting", "gripper", "instrument" or "fluentcontrol".
      Rule: The rule in plain English.
      Basis: "definition", "connector", "observed" or "inference".
    """

    id: str
    category: str
    rule: str
    basis: str


def _float(text: str | None) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _range(group: str, r: dict) -> str:
    if r["min_ul"] is None:
        text = f"{group}: equations without accuracy points"
    else:
        text = f"{group}: {r['min_ul']:g}-{r['max_ul']:g} uL"
    return text + (" multi" if r["multi_dispense"] else "")


class LabCapabilities(sila.Feature):
    """
    Describe what this Fluent can hold and do: the places of the worktable with the labware they accept and how the
    arms reach them, the labware and tip types, the liquid classes usable with the Air FCA arm, the arms and
    instruments, the SiLA commands of this server, the rules a plan must follow, and the current state.

    Read only. Places, labware, tips and liquid classes are read from the FluentControl database on the Fluent PC;
    instruments and rules are kept in this connector, each with its basis. CapabilitiesJson returns everything as one
    JSON document for planning tools.
    """

    def __init__(self, config: CapabilitiesConfig, backend: FluentControlBackend, deck: DeckState | None,
                 features: list[sila.Feature]):
        super().__init__(
            originator="jp.riken.bdr",
            category="tecan.fluent",
            identifier="LabCapabilities",
            name="Fluent - Lab Capabilities",
            version="1.0",
        )
        self.config = config
        self.backend = backend
        self.deck = deck
        self.features = features
        self.worktable = config.worktable or backend.config.definitions.workspace
        self._cache: tuple[float, database.Capabilities] | None = None

    async def _load(self) -> database.Capabilities:
        if self._cache and time.monotonic() - self._cache[0] < self.config.cache_s:
            return self._cache[1]
        try:
            caps = await asyncio.to_thread(database.load, self.config.database_root, self.worktable)
        except (database.DatabaseError, OSError) as exc:
            raise DatabaseUnavailable(str(exc)) from None
        self._cache = (time.monotonic(), caps)
        return caps

    def _places(self, caps: database.Capabilities) -> list[PlaceInfo]:
        return [PlaceInfo(location=p.location, site=p.site, carrier=p.parent,
                          labware=f"{p.labware_type} {p.labware}" if p.labware else "", accepts=p.accepts,
                          gripper_modes=p.gripper_modes,
                          pipetting={True: "yes", False: "no", None: "unknown"}[p.pipetting])
                for p in caps.places]

    def _labware(self, caps: database.Capabilities) -> list[LabwareTypeInfo]:
        out = []
        for c in caps.labware_types():
            wells = c.wells or {}
            out.append(LabwareTypeInfo(
                name=c.name, kind=c.group.removeprefix("Labware."), columns=wells.get("columns", 0),
                rows=wells.get("rows", 0), height_mm=c.height_mm or 0.0, well_volume_ul=wells.get("well_volume_ul") or 0.0,
                grip_narrow_mm=_float(c.attributes.get("Grip_Narrow")), grip_wide_mm=_float(c.attributes.get("Grip_Wide")),
                grip_force=_float(c.attributes.get("Force"))))
        return out

    def _tips(self, caps: database.Capabilities) -> list[TipTypeInfo]:
        racks: dict[str, list[str]] = {}
        for p in caps.places:
            if p.labware_type:
                racks.setdefault(p.labware_type, []).append(f"{p.labware} at {p.location}[{p.site}]")
        return [TipTypeInfo(name=c.name, tip_group=c.attributes.get("DiTiTypeGroup", ""),
                            capacity_ul=_float(c.attributes.get("TipCapacity")),
                            filtered=c.attributes.get("Filter", "").lower() == "true", racks=racks.get(c.name, []))
                for c in caps.tip_types()]

    def _instruments(self, caps: database.Capabilities) -> list[InstrumentInfo]:
        present = {p.parent_type for p in caps.places} | {p.labware_type for p in caps.places}
        return [InstrumentInfo(name=i["name"], kind=i["kind"], on_worktable=i["part"] in present,
                               locations=i["locations"], driver=i["driver"], connection=i["connection"],
                               servers=i["servers"], features=i["features"]) for i in catalog.INSTRUMENTS]

    def _state(self) -> dict:
        state = {"read_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "busy": self.backend.busy,
                 "current_operation": self.backend.current_operation, "run_open": self.backend.run_open,
                 "other_server": self.backend.other_server() or ""}
        if self.deck is not None:
            try:
                state["deck"] = self.deck.load()
            except Exception as exc:  # the deck state is optional here; say why it is missing
                state["deck"] = {"unknown": str(exc)}
        return state

    @sila.UnobservableProperty(errors=[DatabaseUnavailable])
    async def get_places(self) -> list[PlaceInfo]:
        """Every place of the worktable with the labware it accepts, what is on it and how the arms reach it."""
        return self._places(await self._load())

    @sila.UnobservableProperty(errors=[DatabaseUnavailable])
    async def get_labware_types(self) -> list[LabwareTypeInfo]:
        """Labware types that fit some place of the worktable, with wells, height and grip widths."""
        return self._labware(await self._load())

    @sila.UnobservableProperty(errors=[DatabaseUnavailable])
    async def get_tip_types(self) -> list[TipTypeInfo]:
        """FCA tip types with their tip group and capacity, and the racks of each on the worktable."""
        return self._tips(await self._load())

    @sila.UnobservableProperty(errors=[DatabaseUnavailable])
    async def get_liquid_classes(self) -> list[LiquidClassInfo]:
        """Liquid classes, whether they work on the Air FCA arm, and their volume range per tip group."""
        return [LiquidClassInfo(name=lc.name, air_fca=lc.air_fca,
                                tip_groups=[_range(g, r) for g, r in sorted(lc.tip_groups.items())])
                for lc in (await self._load()).liquid_classes]

    @sila.UnobservableProperty()
    async def get_arms(self) -> list[str]:
        """The arms of the instrument, as "<name> (<kind>, <channels> channel(s)): <facts>"."""
        return [f"{a['name']} ({a['kind']}, {a['channels']} channel(s)): " + "; ".join(a["facts"]) for a in catalog.ARMS]

    @sila.UnobservableProperty(errors=[DatabaseUnavailable])
    async def get_instruments(self) -> list[InstrumentInfo]:
        """The instruments of the deck, how they are driven and which SiLA servers and features drive them."""
        return self._instruments(await self._load())

    @sila.UnobservableProperty()
    async def get_commands(self) -> list[CommandInfo]:
        """The SiLA commands this server offers, with their parameters (from the features themselves)."""
        return [CommandInfo(feature=c["feature"], command=c["command"], description=c["description"],
                            parameters=[f"{p['name']} ({p['type']}): {p['doc']}".rstrip(": ") for p in c["parameters"]])
                for c in commands.describe(self.features)]

    @sila.UnobservableProperty()
    async def get_constraints(self) -> list[ConstraintInfo]:
        """Rules a plan for this Fluent must follow (pipetting, gripper, instruments, FluentControl)."""
        return [ConstraintInfo(**c) for c in catalog.CONSTRAINTS]

    @sila.UnobservableProperty()
    async def get_notes(self) -> list[str]:
        """How far the description can be trusted, as "[basis] <note>"."""
        return [f"[{n['basis']}] {n['note']}" for n in catalog.NOTES]

    @sila.UnobservableProperty()
    async def get_current_state_json(self) -> str:
        """The current state as one JSON document: whether a command or run is in progress, whether another server
        holds FluentControl, and the deck state (labware put on, moved or taken off). Changes while the Fluent runs."""
        return json.dumps(await asyncio.to_thread(self._state), ensure_ascii=False)

    @sila.UnobservableProperty(errors=[DatabaseUnavailable])
    async def get_capabilities_json(self) -> str:
        """Everything above as one JSON document (schema "riken-fluent-capabilities/1"), for planning tools."""
        caps = await self._load()
        doc = {
            "schema": SCHEMA,
            "instrument": "Tecan Fluent 780",
            "database": caps.database,
            "worktable": caps.worktable,
            "places": [dataclasses.asdict(p) for p in caps.places],
            "labware_types": [dataclasses.asdict(x) for x in self._labware(caps)],
            "tip_types": [dataclasses.asdict(x) for x in self._tips(caps)],
            "liquid_classes": [dataclasses.asdict(lc) for lc in caps.liquid_classes],
            "arms": catalog.ARMS,
            "rga_settings": caps.rga_settings,
            "instruments": [dataclasses.asdict(x) for x in self._instruments(caps)],
            "commands": commands.describe(self.features),
            "constraints": catalog.CONSTRAINTS,
            "notes": catalog.NOTES,
            "state": await asyncio.to_thread(self._state),
        }
        return json.dumps(doc, ensure_ascii=False)
