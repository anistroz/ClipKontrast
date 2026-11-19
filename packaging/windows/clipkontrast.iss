; ClipKontrast-Setup.exe, built by packaging/windows/build.ps1 (on GitHub's Windows machines, see
; .github/workflows/windows-app.yml). Installs for the current user only: no administrator password, no UAC prompt.
; Everything goes into one folder; the data folder (videos, clips, settings, keys) is never removed or replaced.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C1B2E7A-3F4D-4B8E-9A51-C1F0D2B7E840}
AppName=ClipKontrast
AppVersion={#AppVersion}
AppVerName=ClipKontrast {#AppVersion}
AppPublisher=ClipKontrast (@anistroz.ai)
AppPublisherURL=https://clipkontrast.com
DefaultDirName={localappdata}\Programs\ClipKontrast
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=ClipKontrast-Setup
SetupIconFile=clipkontrast.ico
UninstallDisplayIcon={app}\clipkontrast.ico
UninstallDisplayName=ClipKontrast
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Messages]
WelcomeLabel2=This installs ClipKontrast, the free AI clip maker, on this computer.%n%nEverything it needs comes with it. Your clips stay on your computer.

[InstallDelete]
; A clean copy of the code and its libraries every time; the data folder is left as it is.
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\app.new"
Type: filesandordirs; Name: "{app}\app.old"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\ffmpeg"
Type: filesandordirs; Name: "{app}\update"

[Files]
Source: "..\..\build\ClipKontrast\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\ClipKontrast"; Filename: "{app}\ClipKontrast.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\clipkontrast.ico"
Name: "{autoprograms}\ClipKontrast"; Filename: "{app}\ClipKontrast.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\clipkontrast.ico"

[Run]
Filename: "{app}\ClipKontrast.cmd"; WorkingDir: "{app}"; Description: "Start ClipKontrast now"; Flags: postinstall nowait shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\app.new"
Type: filesandordirs; Name: "{app}\app.old"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\ffmpeg"
Type: filesandordirs; Name: "{app}\update"
