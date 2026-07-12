param(
    [string]$ShortcutName = "Dhyana-95-V2 Camera Control.lnk"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonw = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$icon = Join-Path $projectRoot "assets\wut_logo.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop $ShortcutName

if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "pythonw.exe not found: $pythonw"
}
if (-not (Test-Path -LiteralPath $icon)) {
    throw "Application icon not found: $icon"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "-m tucam_control.main"
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = "Dhyana-95-V2 Camera Control"
$shortcut.Save()

Write-Output $shortcutPath
