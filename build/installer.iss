; Inno Setup Script for ReLIMS Print Service
; Compile with Inno Setup 6+ : https://jrsoftware.org/isinfo.php

[Setup]
AppName=ReLIMS Print Service
AppVersion=1.0.0
AppPublisher=ReLIMS
DefaultDirName={localappdata}\ReLIMS Print Service
DefaultGroupName=ReLIMS Print Service
OutputBaseFilename=relims-print-service-setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\relims-print-service.exe
SetupIconFile=icon.ico

[Files]
Source: "..\dist\relims-print-service.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ReLIMS Print Service"; Filename: "{app}\relims-print-service.exe"
Name: "{group}\Uninstall ReLIMS Print Service"; Filename: "{uninstallexe}"

[Registry]
; Auto-start with Windows (current user only, no admin needed)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "ReLIMS Print Service"; \
    ValueData: """{app}\relims-print-service.exe"""; \
    Flags: uninsdeletevalue

[Run]
Filename: "{app}\relims-print-service.exe"; \
    Description: "Start ReLIMS Print Service now"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/f /im relims-print-service.exe"; \
    Flags: runhidden; RunOnceId: "KillPrintService"
