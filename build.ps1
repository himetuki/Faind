<# 
    Faind PyInstaller build progress display
    PyInstaller writes logs to stderr, so we merge 2>&1 via cmd /c
#>
$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "Faind Build - Running..."

# Build stage mapping (stage -> percentage + display name)
$stageMap = [ordered]@{
    'Analysis'  = @{ Pct = 10; Name = 'Analyzing' }
    'PYZ'       = @{ Pct = 30; Name = 'Building PYZ' }
    'PKG'       = @{ Pct = 55; Name = 'Building PKG' }
    'EXE'       = @{ Pct = 75; Name = 'Building EXE' }
    'COLLECT'   = @{ Pct = 90; Name = 'Collecting' }
    'Appending' = @{ Pct = 97; Name = 'Packing' }
}

$currentStage = 'Analysis'
$currentPct = 0
$barWidth = 35

# Patterns to match PyInstaller build stages (log goes to stderr)
$stagePatterns = @(
    @{ Pattern = 'Building PYZ';         Stage = 'PYZ' },
    @{ Pattern = 'Building PKG';         Stage = 'PKG' },
    @{ Pattern = 'Building EXE from';    Stage = 'EXE' },
    @{ Pattern = 'Building EXE';         Stage = 'EXE' },
    @{ Pattern = 'Building COLLECT';     Stage = 'COLLECT' },
    @{ Pattern = 'Appending archive';    Stage = 'Appending' },
    @{ Pattern = 'Appending PKG';        Stage = 'Appending' }
)

$sw = [System.Diagnostics.Stopwatch]::StartNew()

function Draw-Progress {
    param([string]$stageName, [int]$pct)
    $elapsed = $sw.Elapsed.ToString('hh\:mm\:ss')
    $done = [math]::Floor($pct * $barWidth / 100)
    $left = $barWidth - $done
    $bar  = '[' + ('#' * $done) + ('-' * $left) + ']'
    $eta = '--:--:--'
    if ($pct -gt 0) {
        $remainSec = $sw.Elapsed.TotalSeconds / $pct * (100 - $pct)
        if ($remainSec -lt 86400) {
            $eta = [TimeSpan]::FromSeconds($remainSec).ToString('hh\:mm\:ss')
        }
    }
    $text = "{0} {1,3}%  {2,-12} | Elapsed: {3} | ETA: {4}" -f $bar, $pct, $stageName, $elapsed, $eta
    Write-Host ("`r" + $text) -NoNewline -ForegroundColor Cyan
}

try {
    $tmpLog = "$env:TEMP\faind_build_$pid.log"

    # Run pyinstaller via cmd /c to merge stderr into stdout (PyInstaller logs to stderr!)
    $proc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "pyinstaller Faind.spec --noconfirm 2>&1" `
        -NoNewWindow -PassThru `
        -RedirectStandardOutput $tmpLog

    Write-Host ''
    Write-Host '  PyInstaller log:' -ForegroundColor DarkGray

    $lastMatchIdx = 0

    while (-not $proc.HasExited) {
        Start-Sleep -Milliseconds 300

        if (Test-Path $tmpLog) {
            $content = Get-Content $tmpLog -Raw -ErrorAction SilentlyContinue
            if ($content) {
                $lines = $content -split "`r?`n"
                # Only scan new lines since last match
                for ($i = $lastMatchIdx; $i -lt $lines.Count; $i++) {
                    $line = $lines[$i]
                    # Detect build stage
                    foreach ($pat in $stagePatterns) {
                        if ($line -match $pat.Pattern) {
                            $s = $pat.Stage
                            if ($stageMap.Contains($s)) {
                                $currentStage = $stageMap[$s].Name
                                $currentPct = $stageMap[$s].Pct
                            }
                            break
                        }
                    }
                }
                $lastMatchIdx = $lines.Count
                # Show last meaningful line
                $last = $lines[-1]
                if ($last) {
                    $short = if ($last.Length -gt 78) { $last.Substring(0, 75) + '...' } else { $last }
                    Write-Host ("`r  > " + $short.PadRight(78)) -NoNewline -ForegroundColor DarkGray
                }
            }
        }

        Draw-Progress $currentStage $currentPct
    }

    $proc.WaitForExit()
    $exitCode = $proc.ExitCode
    if ($null -eq $exitCode) { $exitCode = -1 }

    # Did the build actually succeed? Check for the exe
    $exeExists = Test-Path "dist\Faind.exe"

    if ($exitCode -eq 0 -or $exeExists) {
        Draw-Progress 'Done' 100
    } else {
        Draw-Progress 'FAILED' $currentPct
    }
    Write-Host ''
    Write-Host ''

    # Summary
    $total = $sw.Elapsed.ToString('hh\:mm\:ss')
    if ($exitCode -eq 0 -or $exeExists) {
        Write-Host ('  [OK] Total time: ' + $total) -ForegroundColor Green
        $exitCode = 0
    } else {
        Write-Host ('  [FAIL] Elapsed: ' + $total) -ForegroundColor Red
    }

    # Print tail logs on failure
    if ($exitCode -ne 0) {
        Write-Host ''
        Write-Host '  ---- PyInstaller log (last 30 lines) ----' -ForegroundColor Yellow
        if (Test-Path $tmpLog) {
            Get-Content $tmpLog -Tail 30 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkYellow }
        }
    }

    # Cleanup
    Remove-Item $tmpLog -ErrorAction SilentlyContinue

    exit $exitCode
}
catch {
    Write-Host ''
    Write-Host ('  [FATAL] ' + $_.Exception.Message) -ForegroundColor Red
    Remove-Item "$env:TEMP\faind_build_$pid.log" -ErrorAction SilentlyContinue
    exit 1
}
