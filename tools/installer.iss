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

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; The entire built folder: the exe, its _internal bundle, models\, ffmpeg, notices.
; Exclude runtime artifacts a prior local run may have dropped here (the backend log
; now lives in %LOCALAPPDATA%\Vibenative, but be defensive).
Source: "{#DistDir}\*"; DestDir: "{app}"; Excludes: "*.log"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[INI]
; Record the DB-location choice where the app reads it at startup: an exe-adjacent
; settings.ini ([vibenative] db_path). db.py resolves GENRE_DB env > this > default,
; and expands env vars in the value — so a machine-wide setting stays per-user. Power
; users still override everything with the GENRE_DB environment variable.
Filename: "{app}\settings.ini"; Section: "vibenative"; Key: "db_path"; String: "{code:GetDbPath}"

[Code]
var
  DbDirPage: TInputDirWizardPage;

procedure InitializeWizard;
begin
  DbDirPage := CreateInputDirPage(wpSelectDir,
    'Music database location',
    'Where should Vibe Identify keep your library?',
    'Your analyzed tracks, vibes, and tags are stored in a file named genre_v2.db.' + #13#10 +
    'Choose the folder to keep it in — an existing library there will be reused, so an' + #13#10 +
    'upgrade or reinstall keeps all your data. The default is your user-profile folder.',
    False, '');
  DbDirPage.Add('');
  DbDirPage.Values[0] := ExpandConstant('{userprofile}');
end;

function GetDbPath(Param: String): String;
var
  Dir: String;
begin
  Dir := RemoveBackslash(DbDirPage.Values[0]);
  { If left at the default profile folder, store the %USERPROFILE% env var literally
    so the setting resolves per-user at runtime; otherwise store the chosen path. }
  if CompareText(Dir, RemoveBackslash(ExpandConstant('{userprofile}'))) = 0 then
    Result := '%USERPROFILE%\genre_v2.db'
  else
    Result := AddBackslash(Dir) + 'genre_v2.db';
end;
