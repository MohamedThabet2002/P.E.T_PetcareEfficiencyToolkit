[Setup]
; Basic application information
#define MyAppId "{{A1B2C3D4-E5F6-4321-B8A9-0123456789AB}}"
#define MyAppName "PET"
#define MyAppFullName "Petcare Efficiency Toolkit (P.E.T)"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
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
SetupIconFile=assets\icons\app-ico.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=admin
DisableProgramGroupPage=yes
DisableReadyPage=yes

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
function InitializeSetup(): Boolean;
var
  InstalledVer: String;
  UninstallStr: String;
  ResultCode: Integer;
begin
  Result := True;
  InstalledVer := GetInstalledVersion();
  
  if InstalledVer <> '' then
  begin
    // Logic: Only proceed if the current setup version is strictly newer
    if InstalledVer >= '{#MyAppVersion}' then
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
