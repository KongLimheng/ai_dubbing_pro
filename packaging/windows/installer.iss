; ==============================================================================
; Inno Setup Script for AI Dubber Ultimate
; Creates a production Setup Wizard (.exe) for Windows x64
; ==============================================================================

#define MyAppName "AI Dubber Ultimate"
#define MyAppVersion "1.2.9"
#define MyAppPublisher "AI Dubber Team"
#define MyAppURL "https://github.com/heng-dev/ai-dubber-ultimate"
#define MyAppExeName "AI_Dubber_Ultimate.exe"

[Setup]
; Unique AppId generated for AI Dubber Ultimate
AppId={{8B3F9A10-4822-4D91-95BC-5F841C52E761}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\..\dist
OutputBaseFilename=ai-dubber-ultimate-v{#MyAppVersion}-windows-x64-setup
SetupIconFile=..\..\resources\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
DisableProgramGroupPage=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main application binaries and dependencies
Source: "..\..\dist\AI_Dubber_Ultimate\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Default config and runtime manifest
Source: "..\..\runtime_packages.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\resources\*"; DestDir: "{app}\resources"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\resources\icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\resources\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
