# ============================================================
#  刷题匠 PaperDrill —— 一键打包脚本
#  用法： powershell -ExecutionPolicy Bypass -File build_exe.ps1
#  产物： dist\PaperDrill.exe （单文件、免安装、可直接分享）
#
#  v1.3.0 变更：界面改为 Qt（PySide6）。打包时收集 Qt 插件，
#  并在产物上跑一次 --qt-selftest 冒烟验证（用 -SkipSmoke 跳过）。
#
#  可选参数：
#    -SkipTests     跳过测试套件
#    -SkipSmoke     跳过产物冒烟自检
#    -NoClean       不清理 PyInstaller 缓存
#    -OutDir DIR    指定产物目录（默认 dist）。当 dist\PaperDrill.exe 正在运行时，
#                   可先打包到别处（如 -OutDir build\dist_new），关闭程序后再替换。
# ============================================================
param(
    [switch]$SkipTests,
    [switch]$SkipSmoke,
    [switch]$NoClean,
    [string]$OutDir = 'dist'
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host "[1/5] 创建构建虚拟环境 .venv ..." -ForegroundColor Cyan
    python -m venv (Join-Path $root '.venv')
    & $py -m pip install --upgrade pip | Out-Null
}
Write-Host "[1/5] 安装/校验构建依赖 ..." -ForegroundColor Cyan
& $py -m pip install --quiet openpyxl python-docx pypdf pyinstaller pillow "PySide6-Essentials>=6.10,<7"

Write-Host "[2/5] 生成图标 ..." -ForegroundColor Cyan
& $py (Join-Path $root 'tools\make_icon.py')

if (-not $SkipTests) {
    Write-Host "[3/5] 运行测试套件 ..." -ForegroundColor Cyan
    $env:PYTHONIOENCODING = 'utf-8'
    $env:QT_QPA_PLATFORM = 'offscreen'
    Push-Location $root
    & $py -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "测试未通过，已中止打包。" }
    Pop-Location
} else {
    Write-Host "[3/5] 跳过测试（-SkipTests）" -ForegroundColor Yellow
}

Write-Host "[4/5] PyInstaller 打包 ..." -ForegroundColor Cyan

$distDir = Join-Path $root $OutDir
New-Item -ItemType Directory -Path $distDir -Force | Out-Null

# 打包前检查：目标 exe 被正在运行的进程占用会导致 WinError 5
$targetExe = Join-Path $distDir 'PaperDrill.exe'
$running = Get-Process -Name PaperDrill -ErrorAction SilentlyContinue
if ($running -and (Test-Path $targetExe)) {
    $holders = @()
    foreach ($proc in $running) {
        try {
            if ($proc.Path -and ($proc.Path -eq $targetExe)) { $holders += $proc.Id }
        } catch { }
    }
    if ($holders.Count -gt 0) {
        Write-Host ("[中止] 目标产物正被运行中的 PaperDrill.exe 占用（PID: " + ($holders -join ', ') + "），请先关闭程序再打包，或用 -OutDir 指定其它输出目录。") -ForegroundColor Red
        throw "目标 exe 被占用，无法覆盖。"
    }
}
if (Test-Path $targetExe) { Remove-Item $targetExe -Force }

$icon = Join-Path $root 'assets\PaperDrill.ico'
$pyArgs = @(
    '-m', 'PyInstaller',
    '--noconfirm',
    '--onefile',
    '--windowed',
    '--name', 'PaperDrill',
    '--paths', (Join-Path $root 'src'),
    '--distpath', $distDir,
    '--workpath', (Join-Path $root 'build'),
    '--specpath', (Join-Path $root 'build'),
    '--version-file', (Join-Path $root 'packaging\version_info.txt'),
    '--hidden-import', 'openpyxl',
    '--collect-submodules', 'openpyxl',
    '--hidden-import', 'docx',
    '--collect-submodules', 'docx',
    '--collect-data', 'docx',
    '--hidden-import', 'pypdf',
    '--collect-submodules', 'pypdf',
    # ---- Qt 界面（v1.3.0）：插件（platforms/styles/imageformats）必须一起收进来，
    #      否则 exe 启动会报 "could not find or load the Qt platform plugin windows"
    '--collect-all', 'PySide6',
    '--hidden-import', 'paperdrill.ui',
    '--hidden-import', 'paperdrill.ui.application',
    '--hidden-import', 'paperdrill.ui.controller',
    '--hidden-import', 'paperdrill.ui.dialogs',
    '--hidden-import', 'paperdrill.ui.main_window',
    '--hidden-import', 'paperdrill.ui.models',
    '--hidden-import', 'paperdrill.ui.selftest',
    '--hidden-import', 'paperdrill.ui.theme',
    '--hidden-import', 'paperdrill.ui.widgets',
    '--hidden-import', 'paperdrill.ui.pages.practice',
    '--hidden-import', 'paperdrill.ui.pages.exam',
    '--hidden-import', 'paperdrill.ui.pages.exam_run',
    '--hidden-import', 'paperdrill.ui.pages.result',
    '--hidden-import', 'paperdrill.ui.pages.library',
    '--exclude-module', 'numpy',
    '--exclude-module', 'pandas',
    '--exclude-module', 'matplotlib',
    '--exclude-module', 'scipy',
    '--exclude-module', 'PIL',
    '--exclude-module', 'IPython',
    '--exclude-module', 'pytest',
    '--exclude-module', 'setuptools',
    '--exclude-module', 'pip',
    # 未使用的 Qt 子模块（显著减小体积）
    '--exclude-module', 'PySide6.QtWebEngineCore',
    '--exclude-module', 'PySide6.QtWebEngineWidgets',
    '--exclude-module', 'PySide6.QtWebEngineQuick',
    '--exclude-module', 'PySide6.QtQml',
    '--exclude-module', 'PySide6.QtQuick',
    '--exclude-module', 'PySide6.QtQuickWidgets',
    '--exclude-module', 'PySide6.Qt3DCore',
    '--exclude-module', 'PySide6.QtMultimedia',
    '--exclude-module', 'PySide6.QtCharts',
    '--exclude-module', 'PySide6.QtDataVisualization',
    '--exclude-module', 'PySide6.QtPdf',
    '--exclude-module', 'PySide6.QtSql',
    '--exclude-module', 'PySide6.QtNetwork',
    '--exclude-module', 'PySide6.QtDesigner'
)
if (-not $NoClean) { $pyArgs += '--clean' }
if (Test-Path $icon) {
    # 同时嵌入 exe 文件图标与运行时窗口/任务栏图标（application.app_icon_path 从 _MEIPASS/assets 读取）
    $pyArgs += @('--icon', $icon, '--add-data', "$icon;assets")
}
$pyArgs += (Join-Path $root 'launcher.py')

& $py @pyArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败。" }

Write-Host "[5/5] 校验产物 ..." -ForegroundColor Cyan
$exe = Join-Path $distDir 'PaperDrill.exe'
if (-not (Test-Path $exe)) { throw "未找到产物 $exe" }
$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)

if (-not $SkipSmoke) {
    # 用打包产物跑一次 Qt 界面无头自检：能抓到漏收的 Qt 插件与业务回归
    $fixture = Join-Path $root 'fixtures\样例题库.xlsx'
    if (Test-Path $fixture) {
        Write-Host "      冒烟自检（Qt 界面）："
        $smokeOut = Join-Path $env:TEMP ('pd_smoke_' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
        New-Item -ItemType Directory -Path $smokeOut -Force | Out-Null
        $env:QT_QPA_PLATFORM = 'offscreen'
        & $exe --qt-selftest --bank $fixture --out (Join-Path $smokeOut 'progress') --result (Join-Path $smokeOut 'result.json')
        $code = $LASTEXITCODE
        Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
        if ($code -ne 0) {
            Write-Host "[中止] 冒烟自检未通过（退出码 $code），详见 $(Join-Path $smokeOut 'result.json')" -ForegroundColor Red
            throw "产物冒烟自检失败。"
        }
        Write-Host "      冒烟自检通过 ✔" -ForegroundColor Green
    } else {
        Write-Host "      [跳过] 未找到 fixtures\样例题库.xlsx" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "打包完成 ✔" -ForegroundColor Green
Write-Host "  产物：$exe"
Write-Host "  体积：$size MB（Qt 运行库已内含，比 v1.2 的 tkinter 版大属正常）"
Write-Host "  分发：直接复制该 exe 到任意 Windows 10/11 x64 机器即可运行（免安装、免联网）"
Write-Host "  说明：练习进度保存在 %APPDATA%\PaperDrill\progress\"
