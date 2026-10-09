# ============================================================
#  刷题匠 PaperDrill —— 一键打包脚本
#  用法： powershell -ExecutionPolicy Bypass -File build_exe.ps1
#  产物： dist\PaperDrill.exe （单文件、免安装、可直接分享）
# ============================================================
param(
    [switch]$SkipTests,
    [switch]$NoClean
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
& $py -m pip install --quiet openpyxl python-docx pypdf pyinstaller pillow

Write-Host "[2/5] 生成图标 ..." -ForegroundColor Cyan
& $py (Join-Path $root 'tools\make_icon.py')

if (-not $SkipTests) {
    Write-Host "[3/5] 运行测试套件 ..." -ForegroundColor Cyan
    $env:PYTHONIOENCODING = 'utf-8'
    Push-Location $root
    & $py -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "测试未通过，已中止打包。" }
    Pop-Location
} else {
    Write-Host "[3/5] 跳过测试（-SkipTests）" -ForegroundColor Yellow
}

Write-Host "[4/5] PyInstaller 打包 ..." -ForegroundColor Cyan

# 打包前检查：旧产物被正在运行的进程占用会导致 WinError 5
$running = Get-Process -Name PaperDrill -ErrorAction SilentlyContinue
if ($running) {
    Write-Host ("[中止] 检测到正在运行的 PaperDrill.exe（PID: " + (($running | ForEach-Object { $_.Id }) -join ', ') + ")，请先关闭程序再打包。") -ForegroundColor Red
    throw "目标 exe 被占用，无法覆盖。"
}
$oldExe = Join-Path $root 'dist\PaperDrill.exe'
if (Test-Path $oldExe) { Remove-Item $oldExe -Force }

$icon = Join-Path $root 'assets\PaperDrill.ico'
$pyArgs = @(
    '-m', 'PyInstaller',
    '--noconfirm',
    '--onefile',
    '--windowed',
    '--name', 'PaperDrill',
    '--paths', (Join-Path $root 'src'),
    '--distpath', (Join-Path $root 'dist'),
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
    '--exclude-module', 'numpy',
    '--exclude-module', 'pandas',
    '--exclude-module', 'matplotlib',
    '--exclude-module', 'scipy',
    '--exclude-module', 'PIL',
    '--exclude-module', 'PyQt5',
    '--exclude-module', 'PyQt6',
    '--exclude-module', 'PySide2',
    '--exclude-module', 'PySide6',
    '--exclude-module', 'IPython',
    '--exclude-module', 'pytest',
    '--exclude-module', 'setuptools',
    '--exclude-module', 'pip'
)
if (-not $NoClean) { $pyArgs += '--clean' }
if (Test-Path $icon) { $pyArgs += @('--icon', $icon) }
$pyArgs += (Join-Path $root 'launcher.py')

& $py @pyArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败。" }

Write-Host "[5/5] 校验产物 ..." -ForegroundColor Cyan
$exe = Join-Path $root 'dist\PaperDrill.exe'
if (-not (Test-Path $exe)) { throw "未找到产物 $exe" }
$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host ""
Write-Host "打包完成 ✔" -ForegroundColor Green
Write-Host "  产物：$exe"
Write-Host "  体积：$size MB"
Write-Host "  分发：直接复制该 exe 到任意 Windows 10/11 x64 机器即可运行（免安装、免联网）"
Write-Host "  说明：练习进度保存在 %APPDATA%\PaperDrill\progress\"
