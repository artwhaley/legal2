param(
    [string]$VsDevCmd = "C:\Program Files\Microsoft Visual Studio\18\Community\Common7\Tools\VsDevCmd.bat"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$source = Join-Path $repoRoot "third_party\sqlite\spellfix\spellfix.c"
$include = Join-Path $repoRoot "third_party\sqlite\spellfix"
$output = Join-Path $repoRoot "message_evidence_workstation\native\spellfix.dll"

if (!(Test-Path -LiteralPath $VsDevCmd)) {
    throw "Visual Studio developer command not found: $VsDevCmd"
}

New-Item -ItemType Directory -Force -Path (Split-Path $output) | Out-Null

$command = @(
    "call `"$VsDevCmd`" -arch=x64 -host_arch=x64",
    "cl /nologo /O2 /LD /I`"$include`" `"$source`" /Fe`"$output`" /link /EXPORT:sqlite3_spellfix_init"
) -join " && "

cmd /c $command
