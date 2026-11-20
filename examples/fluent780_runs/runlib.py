"""Shared helpers for the serial run scripts in this folder (Fluent 780 at RIKEN BDR).

The scripts send one step at a time to the "Tecan Fluent 780 (All devices)" SiLA2 server (fluent780_all app) and
stop at the first failure. They run on the Fluent PC, next to FluentControl and the UniteLabs FluentControl connector.

Environment:
  FLUENT_SILA_HOST  host of the fluent780_all server (default: 127.0.0.1, then this PC's own IPv4 addresses, since
                    the server may listen on the PC's network address only)
  FLUENT_SILA_PORT  its port (default 50060)

Names below are the labware labels of the worktable WT2411004293_Ver.0.5_OFML and the deck state of 2026-11-19/20.
"""

import os
import re
import socket
import subprocess
import sys
import time

from sila2.client import SilaClient

PORT = int(os.environ.get("FLUENT_SILA_PORT", "50060"))


def _client() -> SilaClient:
    if os.environ.get("FLUENT_SILA_HOST"):
        return SilaClient(os.environ["FLUENT_SILA_HOST"], PORT, insecure=True)
    hosts = ["127.0.0.1"] + [h for h in socket.gethostbyname_ex(socket.gethostname())[2] if not h.startswith("127.")]
    for host in hosts:
        try:
            return SilaClient(host, PORT, insecure=True)
        except Exception:
            continue
    sys.exit(f"no fluent780_all server on port {PORT} at {hosts}; set FLUENT_SILA_HOST")


c = _client()

# labware labels
A, B, TR = "96 Well Flat_Custom[002]", "96 Well Flat_Custom[001]", "4 Well SBS Trough[001]"


def T(n: int) -> str:
    """1.5 ml tube [n] in the POGO rack."""
    return f"1.5ml Sarstedt[{n:03d}]"


R50, R200, R1000 = "FCA_ 50ul SBS[001]", "FCA_ 200ul SBS[003]", "FCA_ 1000ul SBS[002]"
TT = {50: ("FCA, 50ul SBS", R50), 200: ("FCA, 200ul SBS", R200), 1000: ("FCA, 1000ul SBS", R1000)}
S, MULTI, MIX = "Water Free Single", "Water Free Multi", "Water Mix"  # Air FCA liquid classes
CPLC_POGO_SLOT, CPLC_A_SLOT = 1, 3


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def hold_factory(scale: float):
    """hold(seconds, why): sleep for the protocol time multiplied by `scale` (1 = protocol times)."""

    def hold(seconds, why):
        s = seconds * scale
        log(f"wait {s:.0f} s ({why}; protocol {seconds:.0f} s)")
        time.sleep(s)

    return hold


def wait(inst, name, limit=600):
    """Wait for an observable command (or print an unobservable result); exit 1 on an error, 2 on a time-out."""
    t0 = time.time()
    if not hasattr(inst, "done"):
        log(f"{name} -> {inst}")
        return True
    while not inst.done:
        if time.time() - t0 > limit:
            log(f"{name} STILL RUNNING after {limit}s")
            sys.exit(2)
        time.sleep(0.5)
    try:
        r = inst.get_responses()
        log(f"{name} -> {r} {time.time() - t0:.1f}s")
        return r
    except Exception as e:
        log(f"{name} ERROR {type(e).__name__} {str(e)[:700]}")
        sys.exit(1)


def simulation() -> bool:
    """True if the running FluentControl was started with -sim."""
    out = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='SystemSW.exe'\" | Select-Object -ExpandProperty CommandLine",
        ],
        capture_output=True,
        text=True,
    ).stdout
    if not out.strip():
        sys.exit("FluentControl is not running")
    return "-sim" in out


def conn():
    """Client for the UniteLabs FluentControl connector (its port changes when it restarts)."""
    out = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'tecan-fluentcontrol' -and "
            "$_.Name -eq 'python.exe' } | ForEach-Object { Get-NetTCPConnection -State Listen -OwningProcess "
            "$_.ProcessId -ErrorAction SilentlyContinue | ForEach-Object { $_.LocalPort } }",
        ],
        capture_output=True,
        text=True,
    ).stdout.split()
    for p in sorted({int(x) for x in out}):
        try:
            cl = SilaClient("127.0.0.1", p, insecure=True)
            cl.RuntimeController.State.get()
            return cl
        except Exception:
            continue
    sys.exit("UniteLabs FluentControl connector not found")


def ready():
    """Stop unless a run is open, FluentControl is running and no dialog is open."""
    dl = c.Status.ActiveDialogs.get()
    ok = c.RunControl.RunOpen.get() and not dl and c.Status.FluentControlState.get() == "RunModeRunning"
    if not ok:
        log(f"not ready: run open {c.RunControl.RunOpen.get()}, {c.Status.FluentControlState.get()}, dialogs {dl}")
        sys.exit(3)


def next_tip(rack: str) -> str | None:
    """Next tip well of a tip rack in the deck state, e.g. 'C6'."""
    line = [x for x in c.Deck.TipRacks.get() if x.startswith(rack + ":")][0]
    m = re.search(r"next tip ([A-H]\d+)", line)
    return m.group(1) if m else None


def tips_left(rack: str) -> int:
    """Tips left in the rack (column-wise from the next tip); 96 if the deck state says the rack is full."""
    w = next_tip(rack)
    if w is None:
        return 96
    return 96 - ((int(w[1:]) - 1) * 8 + "ABCDEFGH".index(w[0]))


def tips_left_in_column(rack: str) -> int:
    """Tips left in the column of the rack's next tip, e.g. next tip F4 -> 3 (F4, G4, H4)."""
    w = next_tip(rack)
    return 8 - "ABCDEFGH".index(w[0]) if w else 8


def xfer(tip, src, sw, vol, dst, dw, lc=S, mix=None, label=""):
    """One channel: new tip -> aspirate -> dispense -> optional same-well mix (volume, cycles) -> drop."""
    ready()
    print("==", label, flush=True)
    typ, rack = TT[tip]
    if tip in (50, 1000):  # "Set Available Tips" makes ONLY the given well available: set it before every GetTips
        nxt = next_tip(rack) or "A1"
        wait(c.LiquidHandling.SetNextTipPosition(rack, nxt), f"SetNextTipPosition {rack} {nxt}")
    wait(c.LiquidHandling.GetTips(typ, [1], rack), f"GetTips {tip} from {rack}")
    if src is not None:
        wait(c.LiquidHandling.Aspirate(src, [sw], [vol], lc, [1]), f"Aspirate {vol} {src} {sw} ({lc})")
        wait(c.LiquidHandling.Dispense(dst, [dw], [vol], lc, [1]), f"Dispense {vol} {dst} {dw}")
    if mix:
        wait(c.LiquidHandling.Mix(dst, [dw], [mix[0]], MIX, [1], mix[1]), f"Mix {mix[0]}x{mix[1]} {dst} {dw}")
    wait(c.LiquidHandling.DropTips([1]), "DropTips")


def multi(tip, src, src_well, vol, dst, dst_wells, lc=S, mix=None, label=""):
    """Several channels at once (channels 1..n for n wells of one plate column): new tips from the rack (as many as
    are left in its column; the rest in the next round), one aspiration per tip from the same source well (a trough
    lane), one dispense per well, optional same-tip mix, drop. src None: new tips for mixing only.
    The wells of one round must be evenly spaced (e.g. B, D, F: 18 mm), because the channels spread evenly."""
    ready()
    typ, rack = TT[tip]
    todo = list(dst_wells)
    while todo:
        k = min(len(todo), tips_left_in_column(rack))
        wells, todo = todo[:k], todo[k:]
        ch = list(range(1, k + 1))
        print("==", label, wells, flush=True)
        wait(c.LiquidHandling.GetTips(typ, ch, rack), f"GetTips {tip} ch{ch} from {rack}")
        if src is not None:
            wait(
                c.LiquidHandling.Aspirate(src, [src_well] * k, [vol] * k, lc, ch),
                f"Aspirate {vol} x{k} {src} {src_well} ({lc})",
            )
            wait(c.LiquidHandling.Dispense(dst, wells, [vol] * k, lc, ch), f"Dispense {vol} {dst} {wells}")
        if mix:
            wait(
                c.LiquidHandling.Mix(dst, wells, [mix[0]] * k, MIX, ch, mix[1]), f"Mix {mix[0]}x{mix[1]} {dst} {wells}"
            )
        wait(c.LiquidHandling.DropTips(ch), f"DropTips ch{ch}")


def lid_to(lid, loc, site):
    wait(c.Labware.TransferLabware(lid, loc, site), f"{lid} -> {loc}[{site}]")


def lid_back(u, lid, holder):
    """Put a lid back on the plate or rack it belongs to (the holder's cover site)."""
    ix = int(u.RuntimeController.ResolveExpression(f'GetCoverSiteIndex("{holder}")').Result)
    wait(c.Labware.TransferLabware(lid, f'GetCoverSiteName("{holder}")', ix), f"{lid} -> lid of {holder}")


def add_lid(u, name, typ, holder):
    """Register a lid on its plate or rack in the open run (bookkeeping only). Lids the deck state already
    registered at run start are kept."""
    ix = int(u.RuntimeController.ResolveExpression(f'GetCoverSiteIndex("{holder}")').Result)
    inst = c.Labware.AddLabware(name, typ, f'GetCoverSiteName("{holder}")', ix)
    while not inst.done:
        time.sleep(0.3)
    try:
        inst.get_responses()
        log(f"AddLabware {name} on {holder}")
    except Exception as e:
        if "already exists" in str(e):
            log(f"{name} already registered from the deck state (kept)")
        else:
            log(f"AddLabware {name} ERROR {str(e)[:300]}")
            sys.exit(1)


def temp_of(resp) -> float:
    """The temperature in a ReadTemperature response (TemperatureC)."""
    m = re.search(r"Temperature\w*=(-?\d+(?:\.\d+)?)", str(resp))
    if not m:
        raise RuntimeError(f"no temperature in {resp}")
    return float(m.group(1))


def bioshake_settled(target, band=0.5, times=2, every_s=10, timeout_s=1800):
    """Wait until the BioShake reading is within target +- band for `times` readings in a row. It overshoots:
    42 -> 37 C takes about 30 s but dips to about 35.6 C and needs about 90 s to come back (2026-11-20, empty)."""
    t0, hits = time.time(), 0
    while True:
        t = temp_of(wait(c.BioShake.ReadTemperature(), "BioShake.ReadTemperature", limit=180))
        hits = hits + 1 if abs(t - target) <= band else 0
        log(f"BioShake {t:.2f} C (target {target} +- {band}, {hits}/{times})")
        if hits >= times:
            return t
        if time.time() - t0 > timeout_s:
            log("BioShake temperature not settled in time")
            sys.exit(4)
        time.sleep(every_s)
