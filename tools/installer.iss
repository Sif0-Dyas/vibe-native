; Inno Setup script for Vibe Identify — packages dist/Vibe Identify/ into a proper
; Windows installer (Start-menu + optional desktop shortcut, uninstaller).
;
; Build it with:  python tools/build_installer.py   (reads the version from
; vibenative.__version__ and passes it here via /DMyAppVersion=...). You can also run
; iscc directly:  iscc /DMyAppVersion=2.1.0 "tools\installer.iss"
;
; DATA SAFETY (verified): this installer only writes under {app} (Program Files).
;   * The music database lives in %USERPROFILE%\genre_v2.db (default) or wherever
;     GENRE_DB / the DB-location page points — never under {app} — so it is NEVER
;     touched by install, uninstall, or reinstall.
;   * The ONNX models install read-only to {app}\models\. That's fine: the app only
;     READS them, and its exe-adjacent resolution (models_dir()) finds {app}\models
;     with no change. ffmpeg installs the same way, beside the exe.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#ifndef DistDir
  #define DistDir "..\dist\Vibe Identify"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\installer"
#endif

#define MyAppName "Vibe Identify"
#define MyAppExeName "Vibe Identify.exe"
#define MyAppPublisher "Andres Avalos"
#define MyAppURL "https://github.com/Sif0-Dyas/vibe-native"

[Setup]
; A stable AppId ties upgrades + the uninstaller to this product across versions.
AppId={{8E7A1F42-2C9B-4D6E-9A3F-1B5C7D8E0A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
; Install to Program Files -> needs admin; 64-bit only (matches the x64 build).
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=VibeIdentify-Setup-{#MyAppVersion}
SetupIconFile={#SourcePath}\..\desktop\vibe.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
; The dist folder is large (models + ffmpeg); reserve enough headroom in the UI.
DiskSpacePadding=64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; The entire built folder: the exe, its _internal bundle, models\, ffmpeg, notices.
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
