# Fresh execution channels for FluentControl runs

This companion patch applies to the lower UniteLabs FluentControl connector:

- Upstream: https://gitlab.com/unitelabs/connectors/tecan-fluentcontrol
- Tested base: `7fa92cfe3b92bbd6d18be29a96f2e4927a1d8d4` (version 0.5.1).
- Target: `src/unitelabs/tecan_fluentcontrol/io/fluentcontrol_protocol.py`.

The upper connector waits for native `RunModeRunning` before reading `Channel` or
`IsAlive`. Apply this lower patch as well: it discards cached channel references
before preparing an idle runtime and whenever the runtime enters an idle state.
The next operation therefore needs a new `ChannelOpens` callback. If that callback
is absent, startup waits until its timeout.

## Apply and verify

End the active run and confirm native `EditMode` or `RunModeRunFinished`. Keep a
backup of the lower source and any needed recovery records. Review existing local
changes before applying the patch.

From the lower connector checkout, using the absolute path to this repository:

```bash
git rev-parse HEAD
git apply --check /path/to/tecan-fluent/patches/tecan-fluentcontrol/discard-stale-channels.patch
git apply /path/to/tecan-fluent/patches/tecan-fluentcontrol/discard-stale-channels.patch
python /path/to/tecan-fluent/patches/tecan-fluentcontrol/test_channel_cache.py \
  src/unitelabs/tecan_fluentcontrol/io/fluentcontrol_protocol.py
```

The three regression tests extract the actual patched methods with Python's AST
and use inert stand-ins for COM, filesystem deletion, and SiLA subjects. They check
that an idle prepare discards old references before calling native PrepareMethod,
that an active run is preserved when PrepareMethod is refused, and that an idle
transition clears a channel whose close callback was missed.

Restart the lower connector, verify that it is attached and idle, and then restart
the upper connector. On the Fluent PC the corresponding tasks are
`OFML_FluentControlConnector` and `OFML_Fluent780Server`.

## Instrument evidence

The paired upper/lower change was exercised on Fluent 780 on 2026-11-17. A new
SiLA-owned run acquired one 200 uL tip at D1, discarded it, returned the rack lid,
and ended normally. Details and the limits of the comparison are in
[the validation record](../../docs/validation/2026-11-17-fresh-channel.md).
