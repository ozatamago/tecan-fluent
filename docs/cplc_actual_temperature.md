# CPLC actual-temperature reading through FluentControl

`CoolingHeatingPlates.ReadTemperature(Slot)` reads one of the three CPLC positions through the installed `inhecoMTC` legacy driver. It sends only `inhecoMTC_GetTemperature`; it does not set a temperature, enable/disable heating, initialize the instrument, or move an arm.

## Preconditions

- An existing `RunControl.StartRun` session must be open. This command never starts a FluentControl method itself.
- The active INHECO driver configuration must enable the requested slot and expose the driver's known macro IDs: SetTemperature, StartShake, StopShake, Shake, GetTemperature as macro1 through macro5 respectively.
- The current Fluent PC configuration was inspected read-only on 2026-11-17. It exposes only the first four macros. GetTemperature is therefore **not yet enabled on that installation**. The API fails before sending a macro in this state.
- Enable the read macro using the supported Tecan/INHECO driver configuration procedure. The driver INI has a checksum footer; do not append a line manually to a live installation. Reload/restart and definition acceptance are separate deployment steps, not performed by this API.
- `FluentBackendConfig.cplc_driver_ini` points to the active INI, by default `C:\ProgramData\Tecan\VisionX\inhecoMTC.ini`. This setting only identifies a file to read.

## Result

```python
reading = client.CoolingHeatingPlates.ReadTemperature(Slot=1)
# Wait for this observable command as for the other commands.
# Response Reading: Slot, TemperatureC, LogTimestamp, Source
```

TemperatureC is the driver's returned RAT value divided by ten. LogTimestamp is the Fluent PC's local log time, not UTC or a device sampling timestamp. Source identifies the driver command. A dry run, disabled macro/slot, missing/faulted response, wrong-slot record, stale record, or implausible value produces an error. No cached setpoint, zero, or simulated measurement is substituted.

The XML documentation for `GetCurrentTemperature` describes the main PT100 without compensation. Inspection of the installed 2.0.0.56514 driver shows that it sends `<slot>RAT` without a selector. INHECO's firmware manual distinguishes default compensated readings from raw PT100 selectors. The API consequently labels its value as **driver-reported**. It is not a direct measurement inside an Alpaqua tube.

## Implementation and record

The legacy macro receives `slot,,0`: the EVOware output variable is empty. Static inspection shows that an empty variable avoids the unsupported EVOware variable-write branch. `Device.GetTemperature` writes its returned integer to the driver log. The backend records the Fluent PC timestamp before the command, executes the read, then accepts only a fresh completion entry for that slot. Current and recent uncompressed `.ulf` logs are searched. A log rollover that makes the reply unavailable produces an error rather than an older reading.

The operation uses the existing shared backend lock and run, including definition preflight and execution recording. The sensor result or log-read error is included in that record. Failure to collect a result fails the SiLA command even if the macro itself completed. There is no automatic retry of the driver macro.

## Evidence and validation scope

Read-only inspection of the actual Fluent PC found:

- Installed driver DLL: 2.0.0.56514; SHA-256 `520e3de15f19f3c52be3c352b4ad10b091f8a46df4eaae966a9caed4543c77b7`.
- Driver XML documentation SHA-256 `a1b6b947595133ae9777f0b09993074b49cf241a3e82595ed4a5f0c65ced20fd`.
- Driver dispatch ID 4 implements GetTemperature; its command layer calls RAT and its device layer logs the returned integer.
- GetTemperature form accepts the three-field settings string and leaves the output variable empty.

No proprietary DLL, disassembly, active INI, or real experimental log is included in this repository. Tests use synthetic log records matching the inspected method signature.

[INHECO Firmware Command Set, section RAT, page 35](https://www.inheco.com/data/pdf/firmware-command-set-2022-0521-1054-26.pdf)

This change implements the command and tests its contracts, parsing, prerequisites, shared-lock use, and failure behavior offline. Actual end-to-end temperature acquisition remains unverified until the read macro is enabled and the updated server is deployed. The active server was not restarted and no temperature command was sent during development. BioShake and Incubator1 temperature reading are outside this change.
