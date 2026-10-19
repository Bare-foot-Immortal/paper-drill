# ============================================================
#  刷题匠 PaperDrill —— 一键打包脚本
#  用法： powershell -ExecutionPolicy Bypass -File build_exe.ps1 [-Portable]
#  产物： dist\PaperDrill.exe （单文件、免安装、可直接分享）
#         -Portable 时另外产出 dist\PaperDrill-Portable\（文件夹版：
#         启动最快，但必须整个文件夹一起复制/分发）
#
#  v1.3.3 变更：改用 packaging\PaperDrill.spec 打包，不再 --collect-all PySide6。
#  Qt 载荷按实际用到的模块收集，exe 从 98.8 MB 降到约 40 MB；
#  实测窗口就绪：单文件 4.4–5.6 s → 1.8–2.3 s；文件夹版约 1.0–1.3 s。
#
#  可选参数：
#    -SkipTests     跳过测试套件
#    -SkipSmoke     跳过产物冒烟自检
#    -NoClean       不清理 PyInstaller 缓存
#    -OutDir DIR    指定产物目录（默认 dist）
#    -Portable      额外构建文件夹版（dist\PaperDrill-Portable）
# ============================================================
param(
    [switch]$SkipTests,
    [switch]$SkipSmoke,
    [switch]$NoClean,
    [string]$OutDir = 'dist',
    [switch]$Portable
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
    Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
} else {
    Write-Host "[3/5] 跳过测试（-SkipTests）" -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 打包
$distDir = Join-Path $root $OutDir
New-Item -ItemType Directory -Path $distDir -Force | Out-Null
$targetExe = Join-Path $distDir 'PaperDrill.exe'
$portableDir = Join-Path $distDir 'PaperDrill-Portable'
$portableExe = Join-Path $portableDir 'PaperDrill.exe'
$spec = Join-Path $root 'packaging\PaperDrill.spec'

# 打包前检查：目标产物被正在运行的进程占用会导致 WinError 5
$running = Get-Process -Name PaperDrill -ErrorAction SilentlyContinue
if ($running) {
    $holders = @()
    foreach ($proc in $running) {
        try {
            $path = $proc.Path
            if ($path -and (($path -ieq $targetExe) -or
                            ($portableDir -and $path.StartsWith($portableDir, [StringComparison]::OrdinalIgnoreCase)))) {
                $holders += $proc.Id
            }
        } catch { }
    }
    if ($holders.Count -gt 0) {
        Write-Host ("[中止] 目标产物正被运行中的 PaperDrill.exe 占用（PID: " + ($holders -join ', ') + "），请先关闭程序再打包，或用 -OutDir 指定其它输出目录。") -ForegroundColor Red
        throw "目标 exe 被占用，无法覆盖。"
    }
}
if (Test-Path $targetExe) { Remove-Item $targetExe -Force }

Write-Host "[4/5] PyInstaller 打包（单文件）..." -ForegroundColor Cyan
$onefileWork = Join-Path $root 'build\pyi-onefile'
$pyArgs = @('-m', 'PyInstaller', $spec, '--noconfirm',
            '--distpath', $distDir, '--workpath', $onefileWork)
if (-not $NoClean) { $pyArgs += '--clean' }
$env:PAPERDRILL_BUILD_MODE = 'onefile'
try {
    & $py @pyArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包（单文件）失败。" }
} finally {
    Remove-Item Env:\PAPERDRILL_BUILD_MODE -ErrorAction SilentlyContinue
}

if ($Portable) {
    Write-Host "[4/5] PyInstaller 打包（文件夹版，启动更快）..." -ForegroundColor Cyan
    $onedirWork = Join-Path $root 'build\pyi-onedir'
    $tmpDist = Join-Path $root 'build\portable-dist'
    Remove-Item $tmpDist -Recurse -Force -ErrorAction SilentlyContinue
    $pyArgs = @('-m', 'PyInstaller', $spec, '--noconfirm',
                '--distpath', $tmpDist, '--workpath', $onedirWork)
    if (-not $NoClean) { $pyArgs += '--clean' }
    $env:PAPERDRILL_BUILD_MODE = 'onedir'
    try {
        & $py @pyArgs
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包（文件夹版）失败。" }
    } finally {
        Remove-Item Env:\PAPERDRILL_BUILD_MODE -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path (Join-Path $tmpDist 'PaperDrill\PaperDrill.exe'))) {
        throw "未找到文件夹版产物：$tmpDist\PaperDrill\PaperDrill.exe"
    }
    Remove-Item $portableDir -Recurse -Force -ErrorAction SilentlyContinue
    Move-Item (Join-Path $tmpDist 'PaperDrill') $portableDir
    Remove-Item $tmpDist -Recurse -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------- 校验
Write-Host "[5/5] 校验产物 ..." -ForegroundColor Cyan
if (-not (Test-Path $targetExe)) { throw "未找到产物 $targetExe" }
$smokeTargets = @($targetExe)
if ($Portable) {
    if (-not (Test-Path $portableExe)) { throw "未找到文件夹版产物 $portableExe" }
    $smokeTargets += $portableExe
}

if (-not $SkipSmoke) {
    # 用打包产物跑一次 Qt 界面无头自检：能抓到漏收的 Qt 插件与业务回归
    $fixture = Join-Path $root 'fixtures\样例题库.xlsx'
    if (Test-Path $fixture) {
        $env:QT_QPA_PLATFORM = 'offscreen'
        try {
            foreach ($exe in $smokeTargets) {
                $label = Split-Path $exe -Leaf
                if ($exe -ne $targetExe) { $label = "文件夹版 " + (Split-Path (Split-Path $exe -Parent) -Leaf) }
                Write-Host "      冒烟自检（$label）："
                $smokeOut = Join-Path $env:TEMP ('pd_smoke_' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
                New-Item -ItemType Directory -Path $smokeOut -Force | Out-Null
                $resultFile = Join-Path $smokeOut 'result.json'
                # GUI 子系统的 exe 必须用 Start-Process -Wait：用 & 调用是异步的，
                # 会在 result.json 写出来之前就去读它（v1.3.3 打包脚本踩过这个坑）。
                $proc = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList @(
                    '--qt-selftest', '--bank', $fixture,
                    '--out', (Join-Path $smokeOut 'progress'), '--result', $resultFile)
                $code = $proc.ExitCode
                if ($code -ne 0) {
                    Write-Host "[中止] 冒烟自检未通过（退出码 $code），详见 $resultFile" -ForegroundColor Red
                    throw "产物冒烟自检失败：$exe"
                }
                if (-not (Test-Path $resultFile)) {
                    Write-Host "[中止] 冒烟自检未生成结果文件：$resultFile" -ForegroundColor Red
                    throw "产物冒烟自检结果缺失：$exe"
                }
                try {
                    $smoke = Get-Content $resultFile -Raw -Encoding UTF8 | ConvertFrom-Json
                    if (-not $smoke.ok) { throw "result.json ok=false" }
                } catch {
                    Write-Host "[中止] 冒烟自检结果异常：$_" -ForegroundColor Red
                    throw "产物冒烟自检结果异常：$exe"
                }
                Write-Host "      冒烟自检通过 ✔（版本 $($smoke.version)）" -ForegroundColor Green
            }
        } finally {
            Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "      [跳过] 未找到 fixtures\样例题库.xlsx" -ForegroundColor Yellow
    }
}

$size = [math]::Round((Get-Item $targetExe).Length / 1MB, 1)
Write-Host ""
Write-Host "打包完成 ✔" -ForegroundColor Green
Write-Host "  单文件：$targetExe"
Write-Host "  体积：$size MB（Qt 运行库已内含）"
if ($Portable) {
    $portableSize = [math]::Round(
        ((Get-ChildItem $portableDir -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
    Write-Host "  文件夹版：$portableDir（$portableSize MB，启动最快，需整目录分发）"
}
Write-Host "  分发：单文件可直接复制到任意 Windows 10/11 x64 机器运行（免安装、免联网）"
Write-Host "  说明：练习进度保存在 %APPDATA%\PaperDrill\progress\"
