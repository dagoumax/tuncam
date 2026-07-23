param(
    [string]$ShortcutName = "Dhyana-95-V2 Camera Control.lnk"
)

$ErrorActionPreference = "Stop"
$appRoot = (Resolve-Path $PSScriptRoot).Path
$exe = Join-Path $appRoot "Dhyana-95-V2-Camera-Control.exe"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop $ShortcutName

if (-not (Test-Path -LiteralPath $exe)) {
    throw "Application executable not found: $exe"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = $appRoot
$shortcut.IconLocation = "$exe,0"
$shortcut.Description = "Dhyana-95-V2 Camera Control"
$shortcut.Save()

Write-Output $shortcutPath
