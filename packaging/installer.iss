; Inno Setup 6 – inštalátor Anonymizácia dokumentov
; Kompilácia: ISCC.exe packaging\installer.iss  (build.ps1 to robí automaticky)

#define AppName "Anonymizácia dokumentov"
#define AppVersion "0.1.0"
#define AppExe "Anonymizacia.exe"

[Setup]
AppId={{8D1F7C1E-4C0B-4C55-9B7A-6A1E0B2D5A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=
DefaultDirName={autopf}\Anonymizacia
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; bežný používateľ môže inštalovať bez práv správcu; správca môže zvoliť inštaláciu pre všetkých
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Anonymizacia-{#AppVersion}-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "sk"; MessagesFile: "compiler:Languages\Slovak.isl"

[Tasks]
Name: "desktopicon"; Description: "Vytvoriť zástupcu na ploche"; GroupDescription: "Zástupcovia:"

[Files]
Source: "..\dist\Anonymizacia\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Odinštalovať {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Spustiť {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; log aplikácie (config.yaml od správcu ostáva; dokumenty sa nikdy neukladajú)
Type: files; Name: "{localappdata}\anonymizer-sk\anonymizer.log*"
Type: files; Name: "{localappdata}\anonymizer-sk\instance.json"
