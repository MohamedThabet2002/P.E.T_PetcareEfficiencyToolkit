[Setup]
; Basic application information
#define MyAppId "{{A1B2C3D4-E5F6-4321-B8A9-0123456789AB}}"
#define MyAppName "PET"
#define MyAppFullName "Petcare Efficiency Toolkit (P.E.T)"
#ifndef MyAppVersion
  #define MyAppVersion "2.0.0-beta1"
#endif
#define MyAppPublisher "Mohamed Thabet"
#define MyAppExeName "PET.exe"

AppId={#MyAppId}
AppName={#MyAppFullName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppFullName}
DefaultGroupName={#MyAppFullName}
OutputBaseFilename=PET_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardImageFile=assets\installer\wizard_sidebar.bmp
WizardSmallImageFile=assets\installer\wizard_small.bmp
SetupIconFile=assets\icons\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=admin
; The destination-folder page ('Select Destination Location') is shown so the
; user can always change the install directory — click Browse or type a path.
DisableDirPage=no
DisableProgramGroupPage=yes
DisableReadyPage=no
; Install notes (shown just before the destination page) and the
; post-install "what's new" page.
InfoBeforeFile=assets\installer\BEFORE_INSTALL.txt
InfoAfterFile=assets\installer\WHATSNEW.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "assets\installer\Arabic.isl"

[Files]
Source: "dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "ReadME.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "vc_redist.x86.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
; Create a shortcut in the Start Menu
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
; Create a desktop shortcut (optional, user can choose during installation)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}";

[Run]
; Run the application after successful installation
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifdoesntexist
Filename: "{app}\ReadME.txt"; Description: "View the ReadMe file"; Flags: postinstall shellexec skipifdoesntexist
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Microsoft Visual C++ Redistributable x64..."; Check: not IsVCRedist64Installed
Filename: "{tmp}\vc_redist.x86.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Microsoft Visual C++ Redistributable x86..."; Check: not IsVCRedist86Installed

[Code]
const
  AppExeProcess = '{#MyAppExeName}';

// Tell the shell its icon view is stale so desktop/start-menu shortcuts
// re-read the freshly installed executable's icon.
procedure SHChangeNotify(EventID: LongInt; Flags: LongInt; Item1: DWORD; Item2: DWORD);
  external 'SHChangeNotify@shell32.dll stdcall';

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  ExePath: String;
begin
  if CurStep = ssPostInstall then
  begin
    // Refresh Explorer's icon cache so the desktop/start-menu shortcut shows
    // the freshly installed icon right away (Windows caches shortcut icons by
    // target path, so an in-place upgrade can keep the OLD icon). SHCNE_
    // ASSOCCHANGED works on every Windows version; ie4uinit -show is an extra
    // nudge on Win8+. Both run silently here so nothing appears on the wizard.
    SHChangeNotify($08000000, 0, 0, 0);
    ExePath := ExpandConstant('{sys}\ie4uinit.exe');
    if FileExists(ExePath) then
      Exec(ExePath, '-show', '', SW_HIDE, ewNoWait, ResultCode);
  end;
end;

function IsAppProcessRunning(): Boolean;
var
  CmdLine, OutputFile: String;
  ResultCode: Integer;
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := False;
  OutputFile := ExpandConstant('{tmp}\pet_running_check.txt');
  DeleteFile(OutputFile);
  CmdLine := '/c tasklist /FI "IMAGENAME eq ' + AppExeProcess + '" /FO CSV /NH > "' + OutputFile + '"';
  if Exec(ExpandConstant('{cmd}'), CmdLine, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    if LoadStringsFromFile(OutputFile, Lines) then
      for I := 0 to GetArrayLength(Lines) - 1 do
        // The CSV row quotes the process name, e.g. "PET.exe","1234",...
        if Pos(UpperCase('"' + AppExeProcess + '"'), UpperCase(Lines[I])) > 0 then
        begin
          Result := True;
          Exit;
        end;
end;

function GetInstalledVersion(): String;
var
  Version: String;
begin
  Version := '';
  // Check registry locations for the uninstall information (32-bit and 64-bit)
  if not RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + '{#MyAppId}' + '_is1', 'DisplayVersion', Version) then
    if not RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + '{#MyAppId}' + '_is1', 'DisplayVersion', Version) then
       RegQueryStringValue(HKLM64, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + '{#MyAppId}' + '_is1', 'DisplayVersion', Version);
  Result := Version;
end;

function IsVCRedist64Installed: Boolean;
begin
  Result := RegKeyExists(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64');
end;
function IsVCRedist86Installed: Boolean;
begin
  Result := RegKeyExists(HKLM32, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x86');
end;

// --- Semantic version comparison -------------------------------------------
// The old guard compared versions as plain strings ("InstalledVer >= app").
// That is wrong for pre-releases: as strings '2.0.0-beta2' >= '2.0.0-beta1'
// is true (so beta2 would be refused over beta1) and '2.0.0-beta1' >= '2.0.0'
// is also true (so the final release would be refused over a beta). These
// helpers compare dotted numbers first, then a semver pre-release suffix, so
// the ordering is "1.0.0" < "2.0.0-beta1" < "2.0.0-beta2" < "2.0.0".
function PreReleaseRank(const Pre: String): Integer;
begin
  if Copy(Pre, 1, 5) = 'alpha' then Result := 0
  else if Copy(Pre, 1, 4) = 'beta' then Result := 1
  else if Copy(Pre, 1, 2) = 'rc' then Result := 2
  else Result := 0;
end;

function PreReleaseNumber(const Pre: String): Integer;
var
  I: Integer;
  Digits: String;
begin
  Digits := '';
  for I := 1 to Length(Pre) do
    if (Pre[I] >= '0') and (Pre[I] <= '9') then
      Digits := Digits + Pre[I];
  Result := StrToIntDef(Digits, 0);
end;

function ComparePreRelease(const Pre1, Pre2: String): Integer;
var
  R1, R2, N1, N2: Integer;
begin
  // No pre-release outranks any pre-release: 2.0.0 > 2.0.0-beta2.
  if (Pre1 = '') and (Pre2 = '') then begin Result := 0; Exit; end;
  if Pre1 = '' then begin Result := 1; Exit; end;
  if Pre2 = '' then begin Result := -1; Exit; end;

  R1 := PreReleaseRank(Pre1);
  R2 := PreReleaseRank(Pre2);
  if R1 < R2 then begin Result := -1; Exit; end;
  if R1 > R2 then begin Result := 1; Exit; end;

  N1 := PreReleaseNumber(Pre1);
  N2 := PreReleaseNumber(Pre2);
  if N1 < N2 then Result := -1
  else if N1 > N2 then Result := 1
  else Result := 0;
end;

function SplitOctets(const S: String): TArrayOfString;
var
  I, Start: Integer;
  Parts: Integer;
begin
  // TArrayOfString is 0-based; first pass counts the number of parts.
  Parts := 1;
  for I := 1 to Length(S) do
    if S[I] = '.' then Inc(Parts);
  SetArrayLength(Result, Parts);
  Start := 1;
  Parts := 0;
  for I := 1 to Length(S) do
    if S[I] = '.' then
    begin
      Result[Parts] := Copy(S, Start, I - Start);
      Start := I + 1;
      Inc(Parts);
    end;
  Result[Parts] := Copy(S, Start, Length(S) - Start + 1);
end;

function CompareVersions(const V1, V2: String): Integer;
var
  Core1, Core2, Pre1, Pre2: String;
  P1, P2: TArrayOfString;
  I, N, A, B, Dash: Integer;
begin
  Dash := Pos('-', V1);
  if Dash > 0 then begin Core1 := Copy(V1, 1, Dash - 1); Pre1 := Copy(V1, Dash + 1, Length(V1) - Dash); end
  else begin Core1 := V1; Pre1 := ''; end;

  Dash := Pos('-', V2);
  if Dash > 0 then begin Core2 := Copy(V2, 1, Dash - 1); Pre2 := Copy(V2, Dash + 1, Length(V2) - Dash); end
  else begin Core2 := V2; Pre2 := ''; end;

  P1 := SplitOctets(Core1);
  P2 := SplitOctets(Core2);
  N := Length(P1);
  if Length(P2) > N then N := Length(P2);
  for I := 0 to N - 1 do
  begin
    if I < Length(P1) then A := StrToIntDef(P1[I], 0) else A := 0;
    if I < Length(P2) then B := StrToIntDef(P2[I], 0) else B := 0;
    if A < B then begin Result := -1; Exit; end;
    if A > B then begin Result := 1; Exit; end;
  end;

  Result := ComparePreRelease(Pre1, Pre2);
end;

function InitializeSetup(): Boolean;
var
  InstalledVer: String;
  UninstallStr: String;
  ResultCode: Integer;
begin
  Result := True;

  // Refuse to install over a running copy (tasklist is case-insensitive).
  if IsAppProcessRunning() then
  begin
    MsgBox('{#MyAppName} is currently running.' + #13#10#10 +
           'Please close it and run the installer again.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  InstalledVer := GetInstalledVersion();
  
  if InstalledVer <> '' then
  begin
    // Logic: Only proceed if the current setup version is strictly newer
    // (semver comparison, so a beta can upgrade to the next beta and to final).
    if CompareVersions(InstalledVer, '{#MyAppVersion}') >= 0 then
    begin
      MsgBox('A version (' + InstalledVer + ') of {#MyAppName} is already installed.' + #13#10 + 
             'This setup contains version {#MyAppVersion}.' + #13#10#10 +
             'Installation cancelled: The existing version is equal or newer.', mbInformation, MB_OK);
      Result := False;
      Exit;
    end;

    if MsgBox('An older version of {#MyAppName} (' + InstalledVer + ') was detected.' + #13#10 + 
              'It will be uninstalled before upgrading to version {#MyAppVersion}.' + #13#10#10 +
              'Your database and settings will be preserved.' + #13#10 +
              'Do you want to proceed?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      if RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + '{#MyAppId}' + '_is1', 'UninstallString', UninstallStr) or
         RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + '{#MyAppId}' + '_is1', 'UninstallString', UninstallStr) then
      begin
        UninstallStr := RemoveQuotes(UninstallStr);
        // Custom flag /PRESERVEDATA=1 tells the uninstaller not to prompt for data deletion
        if Exec(UninstallStr, '/VERYSILENT /NORESTART /SUPPRESSMSGBOXES /PRESERVEDATA=1', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
        begin
          Result := True;
        end;
      end;
    end
    else
    begin
      Result := False;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataPath: string;
  I: Integer;
  IsUpgrade: Boolean;
begin
  if (CurUninstallStep = usPostUninstall) then
  begin
    // Detect if this uninstallation is part of an upgrade
    IsUpgrade := False;
    for I := 1 to ParamCount do
    begin
      if CompareText(ParamStr(I), '/PRESERVEDATA=1') = 0 then
      begin
        IsUpgrade := True;
        Break;
      end;
    end;

    // Only prompt for data deletion if NOT an upgrade
    if not IsUpgrade then
    begin
      AppDataPath := ExpandConstant('{localappdata}\Petcare Efficiency Toolkit (P.E.T)');
      if DirExists(AppDataPath) then
      begin
        if MsgBox('Would you like to delete your application data (database, settings, and logs)?' + #13#10#10 + 
                  'Warning: This action is permanent.', mbConfirmation, MB_YESNO) = IDYES then
          DelTree(AppDataPath, True, True, True);
      end;
    end;
  end;
end;
