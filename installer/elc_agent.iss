; ELC Agent Inno Setup Installer Script (Phase 32 Plan 32-14, B3, B4, D-32-10, D-32-21)
; 免管理員權限安裝、開機啟動、包含輕量 SoapVoice 客戶端。

[Setup]
AppId={{9F3B5142-26C4-4A8E-8B77-9E467DAE32A1}
AppName=ELC 健保核刪審查工作站
AppVersion=5.2.0
AppPublisher=ELC Medical AI
AppPublisherURL=https://github.com/elc-audit-engine
AppSupportURL=https://github.com/elc-audit-engine
AppUpdatesURL=https://github.com/elc-audit-engine
DefaultDirName={autopf}\ElcAgent
DefaultGroupName=ELC Agent
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ElcAgentSetup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\ElcAgent.exe

[Languages]
Name: "chinesetraditional"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"

[Types]
Name: "full"; Description: "完整安裝 (建議)"
Name: "custom"; Description: "自訂安裝"; Flags: iscustom

[Components]
Name: "main"; Description: "ELC Agent 核心程式與診間快捷列"; Types: full custom; Flags: fixed
Name: "soapvoice"; Description: "SoapVoice 診間語音錄製服務 (由 ElcAgent 自動看管)"; Types: full custom

[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; GroupDescription: "額外捷徑:"
Name: "startupicon"; Description: "開機自動啟動快捷列 (建議)"; GroupDescription: "啟動設定:"

[Files]
Source: "..\dist\ElcAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "..\SoapVoice\dist\SoapVoiceClient\*"; DestDir: "{app}\SoapVoice"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: soapvoice

[Icons]
Name: "{group}\ELC Agent"; Filename: "{app}\ElcAgent.exe"; Components: main
Name: "{group}\解除安裝 ELC Agent"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ELC Agent"; Filename: "{app}\ElcAgent.exe"; Tasks: desktopicon; Components: main
Name: "{userstartup}\ELC Agent"; Filename: "{app}\ElcAgent.exe"; Tasks: startupicon; Components: main

[Run]
Filename: "{app}\ElcAgent.exe"; Description: "立即啟動 ELC Agent"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 解除安裝僅清除安裝目錄下未被覆蓋之遺留暫存檔，保留醫師本機設定與校正檔
Type: files; Name: "{app}\*.log"
