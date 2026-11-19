# Builds ClipKontrast-Setup.exe, the app zip used for updates, and latest.json. Runs on Windows (GitHub's Windows
# machines run it from .github/workflows/windows-app.yml).
#
#   powershell -File packaging/windows/build.ps1 -Version 2026.11.19.1
#
# The folder that gets installed:
#   python\    Python itself (the official "embeddable" build) with every library already installed, and DEPS
#   ffmpeg\    ffmpeg and ffprobe
#   app\       ClipKontrast's code (studio, web, requirements.txt) and VERSION
#   ClipKontrast.cmd, clipkontrast.ico, FFMPEG-LICENSE.txt
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$PythonVersion = "3.12.10",
    [string]$FfmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    [string]$ReleaseBase = "https://github.com/anistroz/clipkontrast/releases/download"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"          # Invoke-WebRequest is many times slower with the progress bar
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Build = Join-Path $Root "build"
$Out = Join-Path $Build "ClipKontrast"
$Dist = Join-Path $Root "dist"
$Cache = Join-Path $Build "cache"
foreach ($d in @($Out, $Dist)) { if (Test-Path $d) { Remove-Item -Recurse -Force $d } }
foreach ($d in @($Out, $Dist, $Cache)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

function Get-File($Url, $Path) {
    if (-not (Test-Path $Path)) {
        Write-Host "Downloading $Url"
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Path
    }
}

# ---- Python, the embeddable build, made able to install libraries and to find ClipKontrast's code
$Py = Join-Path $Out "python"
$pyZip = Join-Path $Cache "python-$PythonVersion-embed-amd64.zip"
Get-File "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" $pyZip
Expand-Archive -Path $pyZip -DestinationPath $Py
$pth = Get-ChildItem $Py -Filter "python*._pth" | Select-Object -First 1
$zipName = (Get-ChildItem $Py -Filter "python*.zip" | Select-Object -First 1).Name
# The search path: the standard library, Python's own folder, the libraries, and ClipKontrast's code next to it.
Set-Content -Path $pth.FullName -Encoding ascii -Value @($zipName, ".", "Lib\site-packages", "..\app", "import site")
$getPip = Join-Path $Cache "get-pip.py"
Get-File "https://bootstrap.pypa.io/get-pip.py" $getPip
& "$Py\python.exe" $getPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "pip could not be installed" }

# ---- the libraries, all of them now, so nothing is installed on the clipper's computer
$req = Join-Path $Root "requirements.txt"
$whisper = (Select-String -Path "$Root\studio\whisper.py" -Pattern '^PACKAGE = "(.+)"').Matches[0].Groups[1].Value
& "$Py\python.exe" -m pip install --no-warn-script-location --disable-pip-version-check -r $req $whisper
if ($LASTEXITCODE -ne 0) { throw "the libraries could not be installed" }
# What these libraries are, so an update knows when it needs the whole installer instead of just the code.
$depsText = (Get-Content $req -Raw) + "`n" + $whisper + "`n" + $PythonVersion
$sha = [System.Security.Cryptography.SHA256]::Create()
$deps = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($depsText.Replace("`r", ""))))).Replace("-", "").ToLower()
Set-Content -Path "$Py\DEPS" -Encoding ascii -Value $deps -NoNewline
# Smaller: compiled caches and pip's own download cache are not needed.
Get-ChildItem $Py -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# ---- ffmpeg
$ffZip = Join-Path $Cache "ffmpeg.zip"
Get-File $FfmpegUrl $ffZip
$ffTmp = Join-Path $Build "ffmpeg-tmp"
if (Test-Path $ffTmp) { Remove-Item -Recurse -Force $ffTmp }
Expand-Archive -Path $ffZip -DestinationPath $ffTmp
$ffBin = (Get-ChildItem $ffTmp -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1).Directory
New-Item -ItemType Directory -Force -Path "$Out\ffmpeg\bin" | Out-Null
Copy-Item "$($ffBin.FullName)\ffmpeg.exe", "$($ffBin.FullName)\ffprobe.exe" "$Out\ffmpeg\bin\"
$ffLicense = Get-ChildItem $ffTmp -Recurse -Filter "LICENSE*" | Select-Object -First 1
$ffVersion = (& "$Out\ffmpeg\bin\ffmpeg.exe" -version | Select-Object -First 1)
@(
    "ClipKontrast includes ffmpeg ($ffVersion), from $FfmpegUrl (built by gyan.dev).",
    "ffmpeg is free software licensed under the GNU GPL version 3. Its source code is at https://ffmpeg.org/download.html",
    "and the build's at https://www.gyan.dev/ffmpeg/builds/ ; ask hello@clipkontrast.com for a copy if it is unavailable.",
    ""
) | Set-Content -Path "$Out\FFMPEG-LICENSE.txt" -Encoding utf8
if ($ffLicense) { Get-Content $ffLicense.FullName | Add-Content -Path "$Out\FFMPEG-LICENSE.txt" -Encoding utf8 }

# ---- ClipKontrast's code
New-Item -ItemType Directory -Force -Path "$Out\app" | Out-Null
Copy-Item -Recurse "$Root\studio" "$Out\app\studio"
Copy-Item -Recurse "$Root\web" "$Out\app\web"
Copy-Item "$Root\requirements.txt", "$Root\LICENSE", "$Root\README.md" "$Out\app\"
Get-ChildItem "$Out\app" -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Set-Content -Path "$Out\app\VERSION" -Encoding ascii -Value $Version -NoNewline
Copy-Item "$PSScriptRoot\ClipKontrast.cmd", "$PSScriptRoot\clipkontrast.ico" "$Out\"

# ---- the update zip: just the code
$appZip = Join-Path $Dist "ClipKontrast-app.zip"
# made by Python, not Compress-Archive: older PowerShell writes the folder names with backslashes, which zip readers
# (and the update check) treat as part of a file name
& "$Py\python.exe" -c "import shutil,sys; shutil.make_archive(sys.argv[1][:-4], 'zip', sys.argv[2])" $appZip "$Out\app"
if ($LASTEXITCODE -ne 0) { throw "the update zip could not be made" }

# ---- the installer
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    choco install innosetup -y --no-progress | Out-Host
    $iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) { throw "Inno Setup is not installed" }
& $iscc "/DAppVersion=$Version" "$PSScriptRoot\clipkontrast.iss"
if ($LASTEXITCODE -ne 0) { throw "the installer could not be built" }
$setup = Join-Path $Dist "ClipKontrast-Setup.exe"

# ---- latest.json: what the installed apps read to know there is a newer version
function Get-Sha($p) { (Get-FileHash -Algorithm SHA256 $p).Hash.ToLower() }
$notes = @()
if (Test-Path "$Root\release-notes.txt") { $notes = @(Get-Content "$Root\release-notes.txt" | Where-Object { $_.Trim() }) }
$manifest = [ordered]@{
    version          = $Version
    app_zip          = "$ReleaseBase/v$Version/ClipKontrast-app.zip"
    app_sha256       = Get-Sha $appZip
    installer        = "$ReleaseBase/v$Version/ClipKontrast-Setup.exe"
    installer_sha256 = Get-Sha $setup
    deps             = $deps
    notes            = $notes
}
# UTF-8 without the byte-order mark Windows PowerShell adds, which JSON readers refuse
[IO.File]::WriteAllText("$Dist\latest.json", ($manifest | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding $false))
Get-ChildItem $Dist | Format-Table Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } } -AutoSize
