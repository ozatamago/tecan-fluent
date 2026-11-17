# Fresh-channel startup validation, 2026-11-17

## Problem and change

After another COM client had used FluentControl, the lower connector retained an
old execution-channel proxy. The upper startup gate accepted a channel called
`ofml` with `IsAlive` before the new native method reached `RunModeRunning`.

In the failed startup trace (JST), RunMethod was called at 15:58:51.973. Channel
properties were read at 15:58:52.190, metadata ExecuteCommand calls followed at
15:58:53.979 and 15:58:54.983, and Running arrived at 15:58:55.221. No new
ChannelOpen was recorded for this attempt. The run became unresponsive before any
lid movement or tip acquisition was submitted. The operator aborted this empty
run.

The upper change delays channel inspection until native Running. The companion
lower patch clears cached proxies before preparing an idle runtime and on idle
transitions. Both changes were applied together, with backups of the deployed
sources. The lower connector remained in its existing COM apartment mode.

A separate deck-bookkeeping issue referenced rack labels that earlier tests had
removed. A metadata-only repair restored the expected baseline labels before the
normal deck-registration sequence. No physical labware was moved by that repair.

## Matched acquisition check

- SiLA-owned run: `20261117-162126`.
- Method: `OFML_ApiHost`, one channel, 200 uL tip type `FCA, 200ul SBS`.
- Source rack: `FCA_ 200ul SBS[001]`, its verified deck position.
- Availability was explicitly set after StartRun: racks 002/003 disabled and rack
  001 positions D1/E1 enabled. Positions A1-C1 had already been consumed.
- The rack lid was parked at the verified Site 2 and returned after disposal.
- No liquid was aspirated or dispensed.

| Operation | Result |
|---|---|
| StartRun and deck registration | Succeeded |
| Three Set Available Tips statements | Succeeded |
| GetTips, channel 1 | Succeeded |
| Native selected rack/index | `FCA_ 200ul SBS[001]`, index 3 (D1) |
| DropTips | Succeeded |
| Rack-lid return | Succeeded |
| EndRun | Succeeded, five upper-layer operations recorded |
| Native final state | RunModeRunFinished, Ready, no active dialogs |

The saved pickup XML SHA-256 was
`99c9c3da24c6f61c101d1161327dc3c88c6f9bc01093585b1e7e19f5b23db54c`.
It matched the saved XML used by the earlier successful direct-COM comparison.
The native trace recorded D1 at 16:24:51.671 JST. After EndRun, the persisted
availability showed E1 remaining and racks 002/003 disabled.

The workspace file read immediately after the setters was an older disk snapshot;
it did not expose the live in-memory inventory at that instant. Setter completion,
the native selected source, and the post-run inventory provide the corresponding
observations.

## Interpretation and remaining scope

The same saved pickup statement succeeded through SiLA in a fresh, explicitly
initialized run. The premature startup gate is a directly observed defect. The
earlier GetTips NullReference is not isolated to one cause: process restart,
channel-lifecycle changes, inventory initialization, and bookkeeping repair were
combined in this successful check.

This validation covers tip acquisition, disposal, and lid return. Tube aspiration,
liquid-volume accuracy, and a complete transformation workflow require their own
checks.

## Automated checks

- Repository test suite: 232 passed.
- Lower source-extraction regression tests: three passed against the patched source.
- The lower patch applies cleanly to the deployed CRLF source at the tested base;
  the resulting Python AST matches the deployed fix.
- All three changed Python files pass Ruff lint and formatting checks.
- Repository-wide Ruff checks retain seven pre-existing lint findings in four
  unchanged files and six pre-existing formatting findings. Those files match
  the baseline commit and are outside this startup change.
