; Inno-Setup-Skript des Studien-Hubs (aufgerufen von build.ps1 mit /DVersion=… /DWurzel=…).
; Installation ohne Adminrechte nach %LOCALAPPDATA%\Programs\StudienHub; Daten liegen getrennt unter
; %LOCALAPPDATA%\StudienHub und bleiben bei Deinstallation erhalten, außer man wählt „Daten löschen“.
; Update: einfach eine neuere Setup-Datei über die alte installieren (gleiche AppId).

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Wurzel
  #define Wurzel ".."
#endif

[Setup]
AppId={{6F1C2A4E-8B3D-4C55-9E2A-5D7B1F3C9A10}
AppName=Studien-Hub
AppVersion={#Version}
AppVerName=Studien-Hub {#Version}
AppPublisher=Studien-Hub
DefaultDirName={localappdata}\Programs\StudienHub
DefaultGroupName=Studien-Hub
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir={#Wurzel}\dist
OutputBaseFilename=StudienHub-Setup-{#Version}
SetupIconFile={#Wurzel}\build\studienhub.ico
UninstallDisplayIcon={app}\StudienHub.exe
UninstallDisplayName=Studien-Hub
; „ultra64“ sprengt den Speicher des 32-Bit-Compilers bei ~350 MB; „max“ in eigenem Prozess passt und ist kaum größer
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=2
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; der laufende Hub wird vorher selbst beendet (PrepareToInstall)
CloseApplications=no
VersionInfoVersion={#Version}

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "autostart"; Description: "Beim Anmelden an Windows starten (im Infobereich)"
Name: "claude"; Description: "In Claude Desktop eintragen (KI-Anbindung, mit Sicherung der Konfiguration)"
Name: "desktop"; Description: "Verknüpfung auf dem Desktop"; Flags: unchecked

[InstallDelete]
; Bibliotheken der Vorversion entfernen, damit keine veralteten Dateien liegen bleiben
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\browser-erweiterung"

[Files]
Source: "{#Wurzel}\build\pyinstaller\StudienHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Browser-Erweiterung an festem Ort (feste ID über den key im Manifest); Edge lädt sie als entpackte Erweiterung
Source: "{#Wurzel}\build\browser-erweiterung\*"; DestDir: "{app}\browser-erweiterung"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Studien-Hub"; Filename: "{app}\StudienHub.exe"; Comment: "Studien-Hub öffnen"
Name: "{userdesktop}\Studien-Hub"; Filename: "{app}\StudienHub.exe"; Tasks: desktop

[Registry]
; Autostart wie im Hub (app/autostart.py): ohne Browserfenster, nur Symbol im Infobereich
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "StudienHub"; ValueData: """{app}\StudienHub.exe"" --hintergrund"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\StudienHub.exe"; Parameters: "--eintragen"; Tasks: claude; Flags: runhidden waituntilterminated; StatusMsg: "Trage den Studien-Hub in Claude Desktop ein …"
Filename: "{app}\StudienHub.exe"; Description: "Studien-Hub öffnen"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\StudienHub.exe"; Parameters: "--austragen"; Flags: runhidden waituntilterminated; RunOnceId: "Austragen"

[Code]
var
  DatenLoeschen: Boolean;

procedure HubBeenden();
var
  Ergebnis: Integer;
begin
  { SQLite im WAL-Modus übersteht das Beenden; offene Schreibvorgänge werden beim nächsten Start ergänzt }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM StudienHub.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Ergebnis);
  Sleep(500);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  HubBeenden();
  Result := '';
end;

{ Autostart nicht gewählt: einen früheren Eintrag (Vorversion oder im Hub eingeschaltet) entfernen }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not WizardIsTaskSelected('autostart') then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'StudienHub');
end;

function InitializeUninstall(): Boolean;
begin
  HubBeenden();
  DatenLoeschen := SuppressibleMsgBox(
    'Sollen auch deine Daten gelöscht werden?' + #13#10#13#10 +
    'Datenbank, heruntergeladene Unterlagen, Modelle, Sicherungen und Logs unter' + #13#10 +
    ExpandConstant('{localappdata}\StudienHub') + #13#10 +
    'sowie die gespeicherten Zugangsdaten.' + #13#10#13#10 +
    '„Nein“ behält alles – eine spätere Installation macht dort weiter.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Ergebnis: Integer;
begin
  { vor dem Entfernen der Programmdateien: die exe löscht die Zugangsdaten noch selbst }
  if (CurUninstallStep = usUninstall) and DatenLoeschen then
    Exec(ExpandConstant('{app}\StudienHub.exe'), '--daten-loeschen', '', SW_HIDE, ewWaitUntilTerminated, Ergebnis);
  if (CurUninstallStep = usPostUninstall) and DatenLoeschen then
    DelTree(ExpandConstant('{localappdata}\StudienHub'), True, True, True);
end;
