# Installs the freshly built ClipKontrast-Setup.exe on this (GitHub) Windows machine and checks it really works:
# every library loads, ffmpeg and Deno are there, clips render with the bundled ffmpeg, and "Update now" goes all
# the way through the launcher (download, swap in the new code, start again). Run by .github/workflows/windows-app.yml.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Dir = "$env:LOCALAPPDATA\Programs\ClipKontrast"
$Base = "http://127.0.0.1:8765"
function Stop-Mine { Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$Dir*" } | Stop-Process -Force }
function Need($cond, $what) { if (-not $cond) { throw "FAILED: $what" } ; Write-Host "PASS $what" }

Start-Process "$Root\dist\ClipKontrast-Setup.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
Start-Sleep -Seconds 8
Stop-Mine            # the installer starts ClipKontrast at the end; this test runs its own copy with test settings
foreach ($f in @("python\python.exe", "python\DEPS", "ffmpeg\bin\ffmpeg.exe", "ffmpeg\bin\ffprobe.exe", "app\studio\server.py",
                 "app\VERSION", "ClipKontrast.cmd", "clipkontrast.ico", "FFMPEG-LICENSE.txt")) {
    Need (Test-Path "$Dir\$f") "installed: $f"
}
Need (Test-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\ClipKontrast.lnk") "Start menu shortcut"
$Py = "$Dir\python\python.exe"
& $Py -c "import sherpa_onnx, faster_whisper, ctranslate2, numpy, soundfile, yt_dlp, yt_dlp_ejs, deno, fastapi, uvicorn, PIL, sqlalchemy; import subprocess; print(subprocess.run([deno.find_deno_bin(), '--version'], capture_output=True, text=True).stdout.splitlines()[0])"
Need ($LASTEXITCODE -eq 0) "every library loads, Deno runs"

# the repository's own tests that use ffmpeg and the downloads, run with the installed Python and ffmpeg
$env:PATH = "$Dir\ffmpeg\bin;$Dir\python\Scripts;$env:PATH"
Push-Location $Root
foreach ($t in @("tests\test_layouts_styles.py", "tests\test_downloads.py", "tests\test_selfupdate.py", "tests\test_languages.py")) {
    & $Py $t
    Need ($LASTEXITCODE -eq 0) "$t on Windows"
}
Pop-Location

# ---- start it the way a person does (the launcher), then update it to a pretend newer version served from here
$old = (Get-Content "$Dir\app\VERSION" -Raw).Trim()
$new = "$old.9999"
$srv = Join-Path $env:RUNNER_TEMP "ck-update"
New-Item -ItemType Directory -Force -Path $srv | Out-Null
Copy-Item "$Root\dist\ClipKontrast-app.zip", "$Root\dist\ClipKontrast-Setup.exe" $srv
$manifest = [ordered]@{
    version = $new; app_zip = "http://127.0.0.1:8799/ClipKontrast-app.zip"
    app_sha256 = (Get-FileHash -Algorithm SHA256 "$srv\ClipKontrast-app.zip").Hash.ToLower()
    installer = "http://127.0.0.1:8799/ClipKontrast-Setup.exe"
    installer_sha256 = (Get-FileHash -Algorithm SHA256 "$srv\ClipKontrast-Setup.exe").Hash.ToLower()
    deps = (Get-Content "$Dir\python\DEPS" -Raw).Trim(); notes = @("Test update")
}
[IO.File]::WriteAllText("$srv\latest.json", ($manifest | ConvertTo-Json), (New-Object System.Text.UTF8Encoding $false))
$web = Start-Process $Py -ArgumentList "-m", "http.server", "8799", "--bind", "127.0.0.1", "--directory", $srv -PassThru -WindowStyle Hidden

$env:CLIPKONTRAST_UPDATE_MANIFEST = "http://127.0.0.1:8799/latest.json"
$env:CLIPKONTRAST_FETCH_MODEL = "0"
$env:CLIPKONTRAST_OPEN_BROWSER = "0"
$launcher = Start-Process "cmd.exe" -ArgumentList "/c", "`"$Dir\ClipKontrast.cmd`"" -PassThru -WindowStyle Hidden
function Wait-Up($seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        try { Invoke-RestMethod "$Base/healthz" -TimeoutSec 3 | Out-Null; return $true } catch { Start-Sleep -Seconds 1 }
    }
    return $false
}
try {
    Need (Wait-Up 180) "ClipKontrast starts from the launcher"
    $st = Invoke-RestMethod "$Base/api/status"
    Need (-not $st.no_ffmpeg) "ffmpeg is found"
    $p = Invoke-RestMethod "$Base/api/update/progress"
    Need ($p.version -eq $old) "running version $old"
    Invoke-RestMethod -Method Post "$Base/api/update/apply" -Headers @{ Origin = $Base } | Out-Null
    $done = $false
    for ($i = 0; $i -lt 180 -and -not $done; $i++) {
        Start-Sleep -Seconds 1
        try { $p = Invoke-RestMethod "$Base/api/update/progress" -TimeoutSec 3; if ($p.version -eq $new) { $done = $true } } catch { }
    }
    Need $done "Update now: downloaded, swapped in by the launcher, started again as $new"
    Need ((Get-Content "$Dir\app\VERSION" -Raw).Trim() -eq $new) "the new code is in place"
    Need (Test-Path "$Dir\app.old\studio\server.py") "the old code was kept aside"
    Need (Test-Path "$Dir\data") "the data folder is outside the code folder"
} finally {
    Stop-Mine
    if ($launcher -and -not $launcher.HasExited) { Stop-Process -Id $launcher.Id -Force -ErrorAction SilentlyContinue }
    if ($web -and -not $web.HasExited) { Stop-Process -Id $web.Id -Force -ErrorAction SilentlyContinue }
}
Write-Host "ALL PASSED"
