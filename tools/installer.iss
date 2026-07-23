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

// Refuse anything below 64-bit Windows 10 version 1903 (build 18362) with a clear
// message, before touching the machine. onnxruntime-directml + WebView2 need it.
function InitializeSetup(): Boolean;
var
  V: TWindowsVersion;
begin
  Result := True;
  if not IsWin64() then
  begin
    MsgBox('Vibe Identify requires 64-bit Windows.' + #13#10 +
      'This machine is running 32-bit Windows, which is not supported.',
      mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end;
  GetWindowsVersionEx(V);
  if (V.Major < 10) or ((V.Major = 10) and (V.Build < 18362)) then
  begin
    MsgBox('Vibe Identify requires 64-bit Windows 10 version 1903 (build 18362) or ' +
      'newer.' + #13#10#13#10 + 'This machine reports Windows ' + IntToStr(V.Major) +
      '.' + IntToStr(V.Minor) + ' (build ' + IntToStr(V.Build) + ').' + #13#10#13#10 +
      'Please update Windows, then run this installer again.', mbCriticalError, MB_OK);
    Result := False;
  end;
end;

{ Read the db_path recorded by a prior install and expand %USERPROFILE% so we can
  default the wizard to it (and target it at uninstall). '' if none/absent. }
function ExistingDbPath(): String;
var
  Raw: String;
begin
  Raw := GetIniString('vibenative', 'db_path', '', ExpandConstant('{app}\settings.ini'));
  if Raw <> '' then
    StringChangeEx(Raw, '%USERPROFILE%', ExpandConstant('{userprofile}'), True);
  Result := Raw;
end;

procedure InitializeWizard;
var
  Prior: String;
begin
  DbDirPage := CreateInputDirPage(wpSelectDir,
    'Music database location',
    'Where should Vibe Identify keep your library?',
    'Your analyzed tracks, vibes, and tags are stored in a file named genre_v2.db.' + #13#10 +
    'Choose the folder to keep it in — an existing library there will be reused, so an' + #13#10 +
    'upgrade or reinstall keeps all your data. The default is your user-profile folder.',
    False, '');
  DbDirPage.Add('');
  { On an upgrade, default to the folder the previous install already uses so the
    user's chosen DB location (and thus their library) is preserved, not reset. }
  Prior := ExistingDbPath();
  if Prior <> '' then
    DbDirPage.Values[0] := ExtractFileDir(Prior)
  else
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

// --- WebView2 runtime -------------------------------------------------------
// The desktop window is Edge WebView2. Windows 11 ships it; some Windows 10 boxes
// don't. Detect the Evergreen runtime (its fixed client GUID) in HKLM (all-users)
// or HKCU (per-user); if absent, download + run Microsoft's Evergreen bootstrapper.
function IsWebView2Runtime(): Boolean;
var
  Pv: String;
begin
  Result := False;
  if RegQueryStringValue(HKLM,
       'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
       'pv', Pv) then
    if (Pv <> '') and (Pv <> '0.0.0.0') then
      Result := True;
  if (not Result) and RegQueryStringValue(HKCU,
       'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
       'pv', Pv) then
    if (Pv <> '') and (Pv <> '0.0.0.0') then
      Result := True;
end;

function OnWv2DownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;  // keep going
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Rc: Integer;
begin
  Result := '';
  if IsWebView2Runtime() then
    Exit;
  try
    // ~2 MB Evergreen bootstrapper; it pulls the runtime itself (needs internet).
    DownloadTemporaryFile('https://go.microsoft.com/fwlink/p/?LinkId=2124703',
      'MicrosoftEdgeWebview2Setup.exe', '', @OnWv2DownloadProgress);
    Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install',
      '', SW_HIDE, ewWaitUntilTerminated, Rc);
  except
    // Offline / blocked: don't abort the install. The app shows a clear message at
    // launch if WebView2 is still missing; the user can install it separately.
  end;
end;

// Uninstall: offer to remove the user's data, defaulting to NO. Never runs on an
// upgrade/reinstall (Inno installs over the existing install folder without invoking
// the uninstaller), and a silent uninstall keeps data untouched.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DbPath: String;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  if UninstallSilent() then
    Exit;
  if MsgBox(
       'Also remove your music database and analysis data?' + #13#10#13#10 +
       'This deletes your analyzed library, vibes, and tags (genre_v2.db) and any' + #13#10 +
       'extracted training clips. Choose No to keep them for a future reinstall.',
       mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    Exit;

  DbPath := ExistingDbPath();
  if DbPath = '' then
    DbPath := ExpandConstant('{userprofile}\genre_v2.db');
  DeleteFile(DbPath);
  DeleteFile(DbPath + '-wal');
  DeleteFile(DbPath + '-shm');
  { extracted section clips + the runtime log dir }
  DelTree(ExpandConstant('{userprofile}\genre_training'), True, True, True);
  DelTree(ExpandConstant('{localappdata}\Vibenative'), True, True, True);
end;
