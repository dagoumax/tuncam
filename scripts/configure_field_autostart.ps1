param(
    [switch]$Remove,
    [string]$ShortcutName = "Dhyana-95-V2 Camera Control.lnk"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup $ShortcutName

if ($Remove) {
    if (Test-Path -LiteralPath $shortcutPath) {
        Remove-Item -LiteralPath $shortcutPath -Force
    }
    Write-Output $shortcutPath
    exit 0
}

$portableExe = Join-Path $projectRoot "Dhyana-95-V2-Camera-Control.exe"
$builtExe = Join-Path $projectRoot "dist\Dhyana-95-V2-Camera-Control\Dhyana-95-V2-Camera-Control.exe"
$pythonw = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$icon = Join-Path $projectRoot "assets\wut_logo.ico"

if (Test-Path -LiteralPath $portableExe) {
    $target = $portableExe
    $arguments = ""
    $workingDirectory = $projectRoot
    $iconLocation = "$portableExe,0"
} elseif (Test-Path -LiteralPath $builtExe) {
    $target = $builtExe
    $arguments = ""
    $workingDirectory = Split-Path -Parent $builtExe
    $iconLocation = "$builtExe,0"
} elseif (Test-Path -LiteralPath $pythonw) {
    $target = $pythonw
    $arguments = "-m tucam_control.main"
    $workingDirectory = $projectRoot
    $iconLocation = "$icon,0"
} else {
    throw "No portable executable or .venv Python runtime was found."
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $workingDirectory
$shortcut.IconLocation = $iconLocation
$shortcut.Description = "Start Dhyana-95-V2 control after Windows sign-in"
$shortcut.Save()

Write-Output $shortcutPath
