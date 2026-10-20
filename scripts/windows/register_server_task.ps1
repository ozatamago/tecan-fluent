# Register the Windows scheduled task OFML_<App>Server that runs one SiLA server of this connector on the Fluent PC
# (scripts/windows/start_connector.ps1). Same form as OFML_StartSila: runs as the logged-on user in session 1, no
# password stored. Starts when that user logs on, and on demand:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\Tecan\OFML\connector\scripts\windows\register_server_task.ps1
#   schtasks /run /tn OFML_Fluent780Server        (start now)
#   schtasks /end /tn OFML_Fluent780Server        (stop)
#
#   ...\register_server_task.ps1 -App bioshake    (task OFML_BioShakeServer, config\bioshake.json)
#
# Without parameters it registers OFML_Fluent780Server for the combined "Tecan Fluent 780 (All devices)" server with
# config.fluent780.json, exactly as before. Task names of the other apps: fluent780 -> OFML_Fluent780OnlyServer (task
# names ignore case, so "Fluent780" is taken by the combined server), odtc -> OFML_OdtcServer, infinite ->
# OFML_InfiniteServer, bioshake -> OFML_BioShakeServer, inheco_incubator -> OFML_InhecoIncubatorServer, cplc ->
# OFML_CplcServer, incubator1 -> OFML_Incubator1Server, colormix_demo -> OFML_ColorMixDemoServer.
#
# A process started from an SSH session ends with that session (2026-10-16), so the server is started this way.
# The ports (50060 and up) are not opened in the firewall: other computers reach them through an SSH tunnel.
param(
  [string]$App = 'fluent780_all',
  [string]$Config = '',
  [string]$Root = 'C:\Users\Tecan\OFML\connector',
  [string]$TaskName = ''
)
$names = @{
  fluent780_all = 'Fluent780'; fluent780 = 'Fluent780Only'; odtc = 'Odtc'; infinite = 'Infinite'; bioshake = 'BioShake'
  inheco_incubator = 'InhecoIncubator'; cplc = 'Cplc'; incubator1 = 'Incubator1'; colormix_demo = 'ColorMixDemo'
}
if (-not $TaskName) {
  $part = $names[$App]
  if (-not $part) { $part = -join ($App -split '_' | ForEach-Object { $_.Substring(0, 1).ToUpper() + $_.Substring(1) }) }
  $TaskName = "OFML_${part}Server"
}
$script = Join-Path $Root 'scripts\windows\start_connector.ps1'
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
if ($App -ne 'fluent780_all') { $arguments += " -App $App" }
if ($Config) { $arguments += " -Config `"$Config`"" }
$a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $Root
$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
       -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $TaskName -Action $a -Principal $p -Trigger $t -Settings $s -Force | Select-Object TaskName, State
