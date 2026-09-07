; Inno Setup script: ImageTagger installer
[Setup]
AppId={{5B3A2E41-6A17-4C6B-9D9A-7C0B9F1D2E4A}
AppName=祭晾屋 image storage
AppVersion=1.3
AppPublisher=
DefaultDirName={autopf}\祭晾屋 image storage
DefaultGroupName=祭晾屋 image storage
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist_setup
OutputBaseFilename=祭晾屋 image storage Setup 1.3
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\ImageTagger.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Files]
; 只安装主体，模型由程序首次运行自动下载（Excludes 排除 eva02）
Source: "dist\ImageTagger\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Excludes: "eva02\*"

[Icons]
; 快捷方式图标直接取 exe 内嵌图标（无需外部 .ico 文件）
Name: "{autodesktop}\祭晾屋 image storage"; Filename: "{app}\ImageTagger.exe"; Tasks: desktopicon
Name: "{autoprograms}\祭晾屋 image storage"; Filename: "{app}\ImageTagger.exe"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标："; Flags: checkedonce

[Run]
Filename: "{app}\ImageTagger.exe"; Description: "立即运行 祭晾屋 image storage"; Flags: nowait postinstall skipifsilent