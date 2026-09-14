; CadBridge 安装脚本（Inno Setup 6）
; ==================================
; 编译：
;   ISCC.exe installer\cadbridge.iss /DMyAppVersion=0.2.0
; 或直接：
;   python build.py --installer      （会带上版本号调 ISCC）
;
; 设计取舍：
;   * 按用户安装（PrivilegesRequired=lowest）—— 不弹 UAC，也不需要管理员权限。
;     代价是只对当前用户可用，对这类个人效率工具是合适的。
;   * 装进 %LOCALAPPDATA%\Programs\CadBridge，符合 VS Code 等现代工具的做法。
;   * 改用户级 PATH（HKCU\Environment），装完直接能敲 cadbridge。
;   * 卸载前必须先停桥接 —— 否则正在运行的 exe 被占用，文件删不掉。

#ifndef MyAppVersion
  #define MyAppVersion "0.2.0"
#endif

#define MyAppName "CadBridge"
#define MyAppPublisher "CadBridge"
#define MyAppExeName "cadbridge.exe"
#define MyAppGuiExeName "cadbridge-gui.exe"
#define MyAppURL "https://github.com/SCRVsck/ClaudetoCAD"

[Setup]
AppId={{8F3A2C41-7B6E-4D9A-9E21-5C4B8A0F1D33}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppSupportURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 按用户安装，不要求管理员
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=CadBridge-{#MyAppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; 卸载/升级前关掉正在运行的实例，避免文件被占用
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinese"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
chinese.NoAutoCAD=安装程序没有在本机检测到 AutoCAD。%n%nCadBridge 本身能装好，但在装上 AutoCAD 之前无法工作。%n%n需要继续吗？
chinese.AutoCADFound=检测到本机已安装 AutoCAD，版本：
chinese.PathNote=已把 CadBridge 加入用户 PATH，重新打开命令行后即可直接使用 cadbridge 命令。
english.NoAutoCAD=AutoCAD was not detected on this machine.%n%nCadBridge will install fine, but cannot work until AutoCAD is installed.%n%nContinue anyway?
english.AutoCADFound=AutoCAD detected on this machine, version:
english.PathNote=CadBridge was added to your user PATH. Open a new terminal to use the cadbridge command.

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#MyAppGuiExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\使用指南.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName} 控制台"; Filename: "{app}\{#MyAppGuiExeName}"
Name: "{group}\{#MyAppName} 自检"; Filename: "{app}\{#MyAppExeName}"; Parameters: "doctor --deep"
Name: "{group}\{#MyAppName} 状态"; Filename: "{app}\{#MyAppExeName}"; Parameters: "info"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
; 装完让用户当场看一眼环境是否就绪（终端保持打开，好看结果）
Filename: "{cmd}"; Parameters: "/k ""{app}\{#MyAppExeName}"" doctor"; \
  Description: "运行自检，确认环境可用"; Flags: postinstall nowait skipifsilent runascurrentuser

[UninstallRun]
; 卸载前先请桥接退场，否则 exe 被占用删不掉。AutoCAD 不受影响。
Filename: "{app}\{#MyAppExeName}"; Parameters: "stop"; \
  Flags: runhidden; RunOnceId: "StopBridge"

[Registry]
; 把安装目录加进用户级 PATH（不污染系统 PATH，也不需要管理员）
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; Check: NeedsAddPath('{app}')

[Code]
const
  EnvironmentKey = 'Environment';

{ --- PATH 处理 ------------------------------------------------------- }

function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKCU, EnvironmentKey, 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  { 前后各加一个分号，避免子串误判（如 C:\App 命中 C:\App2） }
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;

procedure RemoveFromPath(Param: string);
var
  OrigPath, NewPath, UpperParam: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKCU, EnvironmentKey, 'Path', OrigPath) then
    exit;
  UpperParam := Uppercase(Param);
  NewPath := OrigPath;
  P := Pos(';' + UpperParam + ';', ';' + Uppercase(NewPath) + ';');
  if P > 0 then
  begin
    { P 是在加了分号的串上算的，映射回原串的起点 }
    Delete(NewPath, P, Length(Param) + 1);
    if NewPath = ';' then
      NewPath := '';
    RegWriteExpandStringValue(HKCU, EnvironmentKey, 'Path', NewPath);
  end;
end;

{ --- AutoCAD 检测 ---------------------------------------------------- }

function DetectAutoCAD(): string;
var
  Names: TArrayOfString;
  I: Integer;
  Ver: string;
begin
  Result := '';
  if RegGetSubkeyNames(HKLM, 'SOFTWARE\Classes', Names) then
    for I := 0 to GetArrayLength(Names) - 1 do
      if Pos('AUTOCAD.APPLICATION.', Uppercase(Names[I])) = 1 then
      begin
        Ver := Copy(Names[I], Length('AutoCAD.Application.') + 1, 99);
        if (Ver <> '') and (Ver[1] >= '1') and (Ver[1] <= '9') then
          Result := Result + Ver + ' ';
      end;
end;

function InitializeSetup(): Boolean;
var
  Found: string;
begin
  Result := True;
  Found := DetectAutoCAD();
  if Found = '' then
    Result := MsgBox(ExpandConstant('{cm:NoAutoCAD}'), mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Found: string;
begin
  if CurStep = ssPostInstall then
  begin
    Found := DetectAutoCAD();
    if Found <> '' then
      MsgBox(ExpandConstant('{cm:AutoCADFound}') + ' ' + Found, mbInformation, MB_OK);
    MsgBox(ExpandConstant('{cm:PathNote}'), mbInformation, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath(ExpandConstant('{app}'));
end;
