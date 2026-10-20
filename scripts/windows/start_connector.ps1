# Start one SiLA server of this connector on the Fluent PC itself (ssh_target "local": no SSH needed).
# Location on the Fluent PC: C:\Users\Tecan\OFML\connector\scripts\windows\start_connector.ps1
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\Tecan\OFML\connector\scripts\windows\start_connector.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File ...\start_connector.ps1 -App bioshake
#
# -App is the module in src/unitelabs/tecan_fluent/apps (fluent780_all, fluent780, odtc, infinite, bioshake,
# inheco_incubator, cplc, incubator1, colormix_demo). Without parameters it starts the combined "Tecan Fluent 780 (All
# devices)" server with config.fluent780.json in the repository root and logs to C:\Users\Tecan\OFML\connector_state,
# as the task OFML_Fluent780Server always did. For another app the configuration defaults to config\<App>.json (from
# config\<App>.fluentpc.example.json; not in git) and the log to C:\Users\Tecan\OFML\state\<App>.
#
# The repository is cloned to C:\Users\Tecan\OFML\connector and its environment is made with "uv sync". The output goes
# to <LogDir>\server_<time>.log. Only one server with a given UUID may run: stop it on any other computer first.
param(
  [string]$App = 'fluent780_all',
  [string]$Root = 'C:\Users\Tecan\OFML\connector',
  [string]$Config = '',
  [string]$LogDir = ''
)
if ($App -eq 'fluent780_all') {
  # the entry point the task has always used (the same server as apps.fluent780_all:create_app)
  $target = 'unitelabs.tecan_fluent:create_app'
  if (-not $Config) { $Config = Join-Path $Root 'config.fluent780.json' }
  if (-not $LogDir) { $LogDir = 'C:\Users\Tecan\OFML\connector_state' }
} else {
  $target = "unitelabs.tecan_fluent.apps.${App}:create_app"
  if (-not $Config) { $Config = Join-Path $Root "config\$App.json" }
  if (-not $LogDir) { $LogDir = "C:\Users\Tecan\OFML\state\$App" }
}
$uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (-not (Test-Path $uv)) { $uv = 'uv' }
New-Item -ItemType Directory -Force $LogDir | Out-Null
$log = Join-Path $LogDir ('server_' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
Set-Location $Root
"started $(Get-Date -Format s) by $env:USERNAME (session $((Get-Process -Id $PID).SessionId)): $target $Config" | Out-File -Encoding ascii $log
# cmd writes the output as it comes (UTF-8 bytes); PowerShell's own redirection writes UTF-16 and reports the
# server's log lines on stderr as errors
cmd /c "`"$uv`" run connector start --app $target -cfg `"$Config`" >> `"$log`" 2>&1"
