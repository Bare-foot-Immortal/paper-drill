# -*- mode: python ; coding: utf-8 -*-
"""刷题匠 PaperDrill —— PyInstaller spec（裁剪版 Qt 载荷，PyInstaller 6.22）。

设计要点
--------
* 不再使用 ``collect_all('PySide6')``。PyInstaller 自带的 PySide6 钩子会在
  分析到 ``PySide6.QtWidgets`` 时自动收集 Qt6Core/Gui/Widgets/Test DLL、
  platforms/styles/imageformats/iconengines 等插件；collect-all 反而会把
  qml/、translations/、metatypes/、Quick/Qml/Designer DLL、qmlls/assistant
  等用不到的东西一并塞进包里。
* ``hook-PySide6.py`` 还会用 ``collect_extra_binaries()`` 收集
  ``opengl32sw.dll``（20.6 MB，Qt 软件 OpenGL 兜底，Qt Widgets 的 raster
  绘制用不到）。build 后在 TOC 里显式剔除。
* onefile / onedir 由环境变量 ``PAPERDRILL_BUILD_MODE`` 切换：PyInstaller
  在“给 spec 文件”模式下会拒绝 ``--onedir/--onefile`` 这类 makespec 选项，
  ``--distpath/--workpath/--noconfirm`` 仍然有效。

用法（项目根目录，UTF-8 控制台）::

    $env:PAPERDRILL_BUILD_MODE = 'onefile'
    .venv\\Scripts\\python.exe -m PyInstaller build\\expspec\\PaperDrill.spec `
        --noconfirm --distpath build\\exp\\onefile-trim --workpath build\\expwork\\onefile-trim

    $env:PAPERDRILL_BUILD_MODE = 'onedir'
    .venv\\Scripts\\python.exe -m PyInstaller build\\expspec\\PaperDrill.spec `
        --noconfirm --distpath build\\exp\\onedir-trim --workpath build\\expwork\\onedir-trim
"""
import os
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ---------------------------------------------------------------- 路径 / 模式
# SPECPATH 是 spec 文件所在目录；从 packaging/ 或 build/expspec/ 被调用都能
# 向上找到含 launcher.py 的项目根。
ROOT = Path(SPECPATH).resolve()
while ROOT != ROOT.parent and not (ROOT / "launcher.py").is_file():
    ROOT = ROOT.parent

APP_NAME = "PaperDrill"
MODE = os.environ.get("PAPERDRILL_BUILD_MODE", "onefile").strip().lower()
if MODE not in ("onefile", "onedir"):
    raise SystemExit(f"PAPERDRILL_BUILD_MODE must be onefile/onedir, got {MODE!r}")

ICON = str(ROOT / "assets" / "PaperDrill.ico")
VERSION_FILE = str(ROOT / "packaging" / "version_info.txt")
SRC = str(ROOT / "src")

# ---------------------------------------------------------------- datas
datas = [(ICON, "assets")]
datas += collect_data_files("docx")

# ---------------------------------------------------------------- hiddenimports
hiddenimports = [
    # 第三方解析库（源码里是函数内延迟导入，显式列出更稳）
    "openpyxl",
    "docx",
    "pypdf",
    # Qt 界面包：pages 用 __getattr__ 延迟导入，逐一列出
    "paperdrill.ui",
    "paperdrill.ui.application",
    "paperdrill.ui.controller",
    "paperdrill.ui.dialogs",
    "paperdrill.ui.main_window",
    "paperdrill.ui.models",
    "paperdrill.ui.selftest",
    "paperdrill.ui.theme",
    "paperdrill.ui.widgets",
    "paperdrill.ui.pages",
    "paperdrill.ui.pages.practice",
    "paperdrill.ui.pages.exam",
    "paperdrill.ui.pages.exam_run",
    "paperdrill.ui.pages.result",
    "paperdrill.ui.pages.library",
    # Qt 无头自检用到 QtTest（源码里也是函数内导入）
    "PySide6.QtTest",
]
hiddenimports += collect_submodules("openpyxl")
hiddenimports += collect_submodules("docx")
hiddenimports += collect_submodules("pypdf")

# ---------------------------------------------------------------- excludes
excludes = [
    # 未使用的第三方科学栈 / 测试工具
    "numpy",
    "pandas",
    "matplotlib",
    "scipy",
    "PIL",
    "IPython",
    "pytest",
    "setuptools",
    "pip",
    # 未使用的 Qt 子模块（体积大头：WebEngine/Quick/Qml/3D/多媒体…）
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DRender",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSql",
    "PySide6.QtNetwork",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtDBus",
    "PySide6.QtHelp",
    "PySide6.QtSvgWidgets",
]

# ---------------------------------------------------------------- Analysis
a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[SRC],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# ---------------------------------------------------------------- 后处理裁剪
# 钩子自动收进来、但本应用确定用不到的 Qt 载荷。
_TRIM_BASENAMES = {
    "opengl32sw.dll",          # 软件 OpenGL 兜底，Qt Widgets raster 绘制不需要
    "qt6dbus.dll", "qtdbus.pyd",
    "qt6designer.dll", "qtdesigner.pyd", "qt6designercomponents.dll",
    "qt6uitools.dll", "qtuitools.pyd",
}
_TRIM_DIR_PARTS = (
    "pyside6/qml/",
    "pyside6/translations/",
    "pyside6/metatypes/",
    "pyside6/typesystems/",
    "pyside6/include/",
    "pyside6/plugins/designer/",
    "pyside6/plugins/qmltooling/",
)
_TRIM_EXE_RE = re.compile(
    r"^(assistant|qmlls|linguist|lupdate|lrelease|designer|qmlformat|"
    r"qmltyperegistrar|qmlimportscanner|qmlscene|qmltestrunner)\.exe$"
)


def _trim(entries):
    """返回 (保留项, 剔除项)；dest 形如 'PySide6\\plugins\\platforms\\qwindows.dll'。"""
    kept, dropped = [], []
    for entry in entries:
        dest = str(entry[0]).replace("\\", "/").lower()
        base = dest.rsplit("/", 1)[-1]
        if (base in _TRIM_BASENAMES
                or any(part in dest for part in _TRIM_DIR_PARTS)
                or _TRIM_EXE_RE.match(base)):
            dropped.append(entry)
        else:
            kept.append(entry)
    return kept, dropped


a.binaries, _dropped_bin = _trim(a.binaries)
a.datas, _dropped_data = _trim(a.datas)
print(f"[PaperDrill.spec] mode={MODE} root={ROOT}")
print(f"[PaperDrill.spec] trimmed {len(_dropped_bin)} binaries, "
      f"{len(_dropped_data)} data files from Analysis TOC")

# ---------------------------------------------------------------- PYZ / EXE
pyz = PYZ(a.pure)

if MODE == "onedir":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        version=VERSION_FILE,
        icon=ICON,
    )
    COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name=APP_NAME,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        version=VERSION_FILE,
        icon=ICON,
    )
