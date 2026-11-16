param(
    [string]$Adb = "adb",
    [string]$OutputDirectory = ("fingerprint-logs-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
)
$ErrorActionPreference = "Stop"
if (Test-Path -LiteralPath $OutputDirectory) { throw "Output directory already exists." }
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
function Save-Adb([string]$Name, [string[]]$Arguments) {
    $result = & $Adb @Arguments 2>&1
    $code = $LASTEXITCODE
    $result | Out-File -LiteralPath (Join-Path $OutputDirectory $Name) -Encoding utf8
    "exit_code=$code" | Add-Content -LiteralPath (Join-Path $OutputDirectory "exit-codes.txt")
    "$Name : exit $code"
}
Save-Adb "devices.txt" @("devices", "-l")
Save-Adb "getprop.txt" @("shell", "getprop")
Save-Adb "services.txt" @("shell", "service", "list")
Save-Adb "processes.txt" @("shell", "ps", "-A")
Save-Adb "overlay-list.txt" @("shell", "cmd", "overlay", "list", "--user", "0")
Save-Adb "overlay-order.txt" @("shell", "cmd", "overlay", "partition-order")
Save-Adb "overlay-patch.txt" @("shell", "cmd", "overlay", "dump", "io.github.sma1560.fingerprintfix")
Save-Adb "overlay-mtk.txt" @("shell", "cmd", "overlay", "dump", "com.mediatek.frameworkresoverlay")
Save-Adb "lookup.txt" @("shell", "cmd", "overlay", "lookup", "--user", "0", "android", "android:array/config_biometric_sensors")
Save-Adb "lookup-verbose.txt" @("shell", "cmd", "overlay", "lookup", "--user", "0", "--verbose", "android", "android:array/config_biometric_sensors")
Save-Adb "fingerprint.txt" @("shell", "dumpsys", "fingerprint")
Save-Adb "biometric.txt" @("shell", "dumpsys", "biometric")
Save-Adb "logcat.txt" @("logcat", "-d", "-b", "all", "-v", "threadtime")
Write-Output "Saved local diagnostic logs to $OutputDirectory. No enrollment result is inferred."
