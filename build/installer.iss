; Inno Setup Script for ReLIMS Print Manager
; Compile with Inno Setup 6+ : https://jrsoftware.org/isinfo.php
; Pass /DAppVersion=x.y.z from command line to set version

#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif

[Setup]
AppName=ReLIMS Print Manager
AppVersion={#AppVersion}
AppPublisher=ReLIMS
DefaultDirName={localappdata}\ReLIMS Print Manager
DefaultGroupName=ReLIMS Print Manager
OutputBaseFilename=relims-print-manager-setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\relims-print-manager.exe
#ifexist "icon.ico"
SetupIconFile=icon.ico
#endif

[Files]
Source: "..\dist\relims-print-manager.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\relims-print-service.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\relims-self-updater.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ReLIMS Print Manager"; Filename: "{app}\relims-print-manager.exe"
Name: "{group}\Uninstall ReLIMS Print Manager"; Filename: "{uninstallexe}"

[Registry]
; Auto-start the manager on login (it will start the print service)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "ReLIMS Print Manager"; \
    ValueData: """{app}\relims-print-manager.exe"""; \
    Flags: uninsdeletevalue

[Run]
Filename: "{app}\relims-print-manager.exe"; \
    Description: "Start ReLIMS Print Manager now"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; Kill both processes before uninstalling
Filename: "taskkill"; Parameters: "/f /im relims-print-manager.exe"; \
    Flags: runhidden; RunOnceId: "KillManager"
Filename: "taskkill"; Parameters: "/f /im relims-print-service.exe"; \
    Flags: runhidden; RunOnceId: "KillPrintService"

[UninstallDelete]
; Clean up staging directory
Type: filesandordirs; Name: "{app}\staging"
