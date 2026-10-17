# 刷题匠 PaperDrill

> 题库刷题练习 + 模拟考试的桌面工具：实时判题、错题本、**进度自动保留**、
> **按题型练习**、**自定义蓝图生成试卷并真实模拟考试**。
>
> **v1.3.0 起界面改为 Qt（PySide6）**：卡片式布局、深浅主题、高 DPI 缩放；
> PySide6 不可用时自动回退 tkinter 界面，两套界面共用同一份进度与配置。

- **交付形态**：Windows 单文件 exe（`dist/PaperDrill.exe`），免安装、免联网、可直接分享
- **界面语言**：简体中文 ｜ **版本**：1.3.2 ｜ exe 体积约 90–100 MB（Qt 运行库内含）
- **本版定位**：练习 + 模拟考试，**不含试卷导出**（导出正式试卷请用组卷版）
- **新增能力（v1.3.x）**：
  - **现代 Qt 界面**：左侧主导航 + 顶栏统计 + 卡片式题面；选项整行可点、判定后正确项标绿、
    错选项标红、无关项弱化；环形进度；成绩页含得分头图与逐题明细
  - **深色 / 浅色 / 跟随系统** 三档主题，切换即时生效并持久化
  - **高 DPI**：125%/150%/200% 缩放下布局不重叠
  - **Qt 无头自检** `--qt-selftest`：无人值守跑完整闭环并输出 JSON
  - **v1.3.1 题目导览**：「本范围进度」下方是 5 列题号方格，点击跳题，
    答对绿 / 答错红 / 未答灰，当前题高亮，题多时内部滚动
  - **v1.3.1 练习位置按模式记忆**：顺序 / 随机 / 错题重练 / 只练未做之间切换、以及按题型范围切换，
    切走再切回来仍停在各自上次的位置（按题目指纹恢复）
  - **v1.3.1 布局合并**：提交答案 / 不会看答案 / 上一题 / 下一题并入题卡底部；
    快捷键提示移到页面最下方的一长条
  - **v1.3.2 图标修复**：窗口标题栏、任务栏与 exe 文件统一显示「刷题匠」图标
    （源码运行与单文件 exe 都能正确读取 `assets/PaperDrill.ico`）
- **缺陷修复**：
  - v1.3.0 —— 勾选「单选/多选打乱选项」等触发重绘的操作会让旧选项行短暂变成顶层窗口，
    表现为屏幕"闪一下小窗"；已改为先隐藏再摘除，并加入自检项 `no_popup_flash`
    （去掉修复后该自检与回归用例必红）
  - v1.3.1 —— 切换练习模式/范围后切回来会回到第 1 题；已改为按（模式, 范围）组合键
    分别落盘位置窗口，切换时先存旧位置、再按指纹恢复目标位置
  - v1.3.2 —— 打开软件后窗口/任务栏不显示软件图标；已修正图标资源路径，
    并把 ico 一并打进单文件 exe 的运行时资源
- **沿用能力**：题库导入（Excel/CSV/TXT/JSON/Word/PDF）、练习范围与模式、选项打乱、
  试卷蓝图、一轮覆盖、模拟考试、错题本、题库删减、题库选择、进度延续

| 配套版本 | 目录 | 用途 |
|---|---|---|
| 抽题匠 PaperForge v1.0.0 | `../PaperForge/` | 随机组卷、一轮覆盖、**导出 Word/HTML/TXT 试卷** |
| **刷题匠 PaperDrill v1.3.2（本版）** | `./` | 实时练习、按题型练习、模拟考试、进度保留 |

两版互不影响，可同时安装使用。

---

## 功能速览

| 需求 | 实现 |
|---|---|
| 三种题型 | 单选题 / 多选题 / 判断题 |
| 实时答题 | 单选/判断点选即判，多选提交判；立刻显示对错、正确答案、解析 |
| **练习范围** | 整个题库 / 只练单选 / 只练多选 / 只练判断，可与练习模式叠加 |
| 练习模式 | 顺序 / 随机 / 错题重练 / 只练未做 |
| **试卷蓝图自定义** | 每卷各题型数量任意设置（如 20/10/10），分值可调 |
| **一轮覆盖** | 轮长 = max(⌈题库量÷每卷量⌉)；末卷不足时从本轮已出现题目随机补足 |
| **模拟考试** | 按蓝图生成一轮试卷 → 选卷作答（全程无对错提示）→ 交卷评分 → 逐题解析 |
| **单选/多选打乱分离** | 两个独立开关；标注「（定）」的题目永不打乱 |
| 进度保留 | 每答一题即时落盘；题库增删/改名/换目录后进度仍保留；多题库隔离 |
| 进度延续 | 恢复位置按题目指纹定位：随机 / 只练未做等模式重开仍停在关闭前那道题 |
| 题库删减 | 按题库剔除不想练的题目（练习、错题本、组卷都不再出现），不改原文件，可随时恢复 |
| 题库选择 | 记住最近用过的题库，一键切换 / 扫描文件夹 / 从列表移除（不删文件） |
| 错题本 | 答错自动入本（练习与考试都算），答对自动移出 |
| 历史成绩 | 最近 30 次模拟考试成绩（时间、卷号、得分、正确率） |
| **界面主题** | 深色 / 浅色 / 跟随系统，即时切换并记住选择 |
| 无导出 | 本版明确不导出试卷（由组卷版承担） |

## 快速使用

1. 双击 `dist/PaperDrill.exe`；
2. 「导入题库…」选择 Excel（列头：题型 / 题目标题 / 选项A…选项H / 解析 / 答案；
   题库模板导出的 `试题正文 / 试题选项 / 试题答案` 单列版式同样支持），
   也可以把题库文件**直接拖到窗口上**；
3. **练习页**：选范围 + 模式，直接答题；
4. **模拟考试页**：设蓝图 → 生成一轮试卷（自动校验覆盖）→ 选卷 → 开始考试 → 交卷看成绩；
5. 关掉再打开，自动接着上次继续。

详细说明见 [使用说明.md](使用说明.md)。

## 界面结构（v1.3.2）

```
┌──────────┬─────────────────────────────────────────────────────────────┐
│ 刷题匠    │ 当前题库名                        [已练][正确率][错题]       │  ← 顶栏
│          ├─────────────────────────────────────────────────────────────┤
│ ▸ 练习    │  练习范围 [整个题库▾]  练习模式 [顺序练习▾]  ☑打乱 ☑解析     │
│   模拟考试 │  ┌───────────────────────────────────┐  ┌───────────────┐ │
│   题库资料 │  │ 12. 题干文本…                      │  │ ◔ 42%  30/52  │ │
│          │  │ ┌───────────────────────────────┐  │  │ 答对/答错/错题 │ │
│          │  │ │ A. 选项                ✔      │  │  ├───────────────┤ │
│          │  │ └───────────────────────────────┘  │  │ 题目导览 本轮52│ │
│          │  │ ✔ 回答正确！正确答案：A             │  │ [1][2][3][4][5]│ │
│          │  │ ───────────────────────────────  │  │ [6][7][8][9][…]│ │
│          │  │ [提交答案][不会看答案]  [◀][下一题▶] │  │  …内部滚动…    │ │
│          │  └───────────────────────────────────┘  └───────────────┘ │
│ [主题▾]   ├─────────────────────────────────────────────────────────────┤
│          │ 快捷键  1~8/A~H 选项 · Enter 提交/下一题 · ←→ 翻题 · F5/F9   │  ← 底部通栏
└──────────┴─────────────────────────────────────────────────────────────┘
```

## 目录结构

```
PaperDrill/
├─ src/paperdrill/
│  ├─ models.py         题型/题目模型、答案解析（含「定」标记）
│  ├─ bank_io.py        xlsx/csv/txt/json/docx/pdf 解析、列头识别、段落解析、坏行报告
│  ├─ store.py          进度存储：题库标识、按题目指纹记录、成绩单、题库变更继承、原子写入
│  ├─ paper.py          试卷蓝图 + 轮次覆盖抽题 + 末卷补题
│  ├─ practice.py       练习范围/模式、打乱、判题、模拟考试与评分
│  ├─ config.py         界面偏好（蓝图、分值、打乱、范围、主题）
│  ├─ ui/               ★ v1.3.0 新增：Qt 界面
│  │  ├─ controller.py   会话控制器（唯一状态源 + Qt 信号，UI 无关、可无头测试）
│  │  ├─ theme.py        设计令牌 / QSS 生成 / 主题切换 / 对比度校验
│  │  ├─ widgets.py      卡片、选项行（自绘）、环形进度、分段控件、成绩头图
│  │  ├─ models.py       QAbstractTableModel（试卷明细/逐题/成绩/题库/进度）
│  │  ├─ pages/          练习页、考试配置页、考试作答页、成绩页、题库资料页
│  │  ├─ dialogs.py      错题本/题库删减/进度管理/选择题库/历史成绩/说明
│  │  ├─ main_window.py  导航、菜单、快捷键、状态栏、几何持久化、拖放
│  │  ├─ application.py  QApplication 创建与高 DPI 设置
│  │  └─ selftest.py     ★ Qt 无头自检（发布验收）
│  ├─ qt_app.py         ★ Qt 门面：可用性检测与回退判断
│  ├─ gui.py            tkinter 界面（回退实现，功能冻结）
│  ├─ cli.py            题库统计、进度列表、无界面练习/组卷/考试、日志
│  └─ __main__.py       入口分发（优先 Qt，缺失时回退 tkinter）
├─ tests/                   测试集（领域层 + tkinter 回退 + Qt 表现层）
├─ tools/                   图标/样例/测试健康检查脚本
├─ packaging/version_info.txt
├─ launcher.py              打包入口脚本
├─ build_exe.ps1            一键打包（含 Qt 冒烟自检）
├─ samples/示例题库.*        示例题库（含 1 道「（定）」题）
├─ fixtures/                合成测试夹具（52 题、Word/PDF 样例）
├─ docs/                    需求 / 设计 / 测试报告 / 缺陷分析 / UI 改造文档
└─ dist/PaperDrill.exe      ★ 最终交付产物
```

## 核心算法（一句话版）

**组卷**：按题型各自把题库洗牌成一副牌，第 i 张卷切第 i 块（块长 = 该题型每卷配额）；
切到最后一块不足时，剩余题目先放进去，差额从**本轮已出现过的同题型题目**中随机抽补。
因此一轮 N = max(⌈题库量÷配额⌉) 张之后，题库必然被完整覆盖，且每张卷题量恒定。

**考试**：按上面生成的整卷作答，作答期间不给任何对错信息，交卷时一次性评分；
未答按错误计分并单列；考试成绩与练习共用同一份进度（错题本同步更新）。

## 进度保留的实现要点

```
进度文件 = %APPDATA%\PaperDrill\progress\<题库文件名>__<全库题目指纹摘要>.json
题库库   = %APPDATA%\PaperDrill\library.json      ← 最近用过的题库（只记路径，不删文件）
界面偏好 = %APPDATA%\PaperDrill\settings.json     ← 含主题、蓝图、窗口位置
记录键   = sha1(题干 + 选项)[:12]        ← 与行号、顺序无关
```

- **题库增删题目**：内容未变的记录全部保留（按指纹匹配）；
- **题库改名/换目录**：按**内容重合度 ≥ 60%** 自动继承旧进度并另存为新文件（旧文件保留）；
- **恢复位置**：落盘 `pos_fps` 导航窗口（当前位置 + 其后 3 题），恢复时按指纹依次匹配；
  并按 `（练习模式, 练习范围）` 组合键分别记忆，切换模式/范围后切回来仍停在各自主次位置；
- **题库删减**：`excluded` 指纹集合存在同一份进度文件里，练习/错题本/统计/组卷统一过滤；
- **写入安全**：临时文件 + `os.replace` 原子替换；进度文件损坏时以空进度启动；
- **版本兼容**：v1.2.x 的进度与配置可直接被 v1.3.x 读取（新增字段缺省为空）。

## 本版验证结果（v1.3.2 实测）

| 项 | 命令 / 方式 | 结果 |
|---|---|---|
| Qt 界面 + 新增回归 | `pytest tests\test_qt_controller.py tests\test_position_memory.py tests\test_qt_practice.py tests\test_qt_navigator.py tests\test_qt_icon.py tests\test_qt_shortcuts.py tests\test_qt_theme.py tests\test_qt_exam.py tests\test_qt_dialogs.py -v` | **199 passed** |
| 领域层回归 | `pytest tests\test_paperdrill.py::TestPracticeSession ::TestProgressStore ::TestBuildItem tests\test_review_fixes.py tests\test_import_layouts.py tests\test_word_pdf_import.py -v` | **129 passed** |
| Qt 无头自检测试 | `pytest tests\test_qt_selftest.py -v` | **11 passed**（完整闭环 ok=true） |
| tkinter 模式切换回归 | `pytest tests\test_paperdrill.py::TestRedoAnsweredQuestions -v` | **9 passed** |
| 代码检查 | `python -m ruff check src tools tests` | **All checks passed** |
| Qt 无头自检 | `python -m paperdrill --qt-selftest --bank fixtures\样例题库.xlsx` | **ok=true，stage=done** |
| 产物冒烟 | `dist\PaperDrill.exe --qt-selftest …` | **exit=0，ok=True**，窗口标题 v1.3.2 |
| 产物版本 | exe 文件属性 | **1.3.2.0**（与界面、README 一致） |
| 产物 CLI | `dist\PaperDrill.exe --bank … --stats-only` | **exit=0，正确解析 52 题** |
| 真实题库验收 | 308 题题库：第 50 题 → 随机 → 顺序、范围往返、错题重练（空）往返、只练未做往返、重开软件 | **全部回到原题/原位** |
| 外观验收 | 离屏渲染 + 真实窗口实拍（浅色 / 深色 / 1024×700 / 空态 / 第 50 题跳转） | 导览 5 列、当前格高亮、内部滚动、按钮在题卡底部、底栏通栏均正常 |

四项改动的设计、数据结构与兼容性说明见
[练习位置记忆与练习页布局改造](docs/11-练习位置记忆与练习页布局改造.md)；
本次练习页实拍见 [docs/screenshots/11-practice-navigator.png](docs/screenshots/11-practice-navigator.png)。

界面截图（浅色 / 深色 / 答错反馈 / 考试 / 成绩）可直接看
[Qt 界面测试报告](docs/10-Qt界面测试报告.md) 第 6 章。

## 从源码运行

```powershell
python -m venv .venv
.venv\Scripts\pip install openpyxl python-docx pypdf "PySide6-Essentials>=6.10,<7"
$env:PYTHONPATH="src"
python -m paperdrill                 # 启动 Qt 界面（PySide6 缺失时自动回退 tkinter）
python -m paperdrill --gui 题库.xlsx  # 指定题库启动

# 测试（Qt 测试自动使用 offscreen 平台，无需显示环境）
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest discover -s tests
```

## 重新打包 exe

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1
# 跳过测试加速： -SkipTests    跳过产物冒烟自检： -SkipSmoke
# 产物正被运行中的程序占用时，先打包到别处： -OutDir build\dist_new
```

产物：`dist\PaperDrill.exe`（约 90–100 MB，单文件，Qt 运行库内含）。

> 注意：更新 exe 前必须先**关闭正在运行的 PaperDrill**，否则 `dist\PaperDrill.exe` 被占用、
> 替换会失败（脚本会明确中止并提示 PID）。临时验证可用 `-OutDir build\dist_new` 另存一份。

> 体积比 v1.2 的 tkinter 版（约 13 MB）大是必然代价：Qt 的 `Qt6Core/Qt6Gui/Qt6Widgets`
> 及其平台插件必须一起打包。构建脚本已排除 WebEngine/Qml/Quick/Multimedia 等未用模块。

## 命令行

```bat
PaperDrill.exe --bank 题库.xlsx --stats-only
PaperDrill.exe --progress-dir 目录 --list-progress
PaperDrill.exe --bank 题库.xlsx --progress-dir 目录 --practice 10 --mode wrong
PaperDrill.exe --bank 题库.xlsx --plan --single 20 --multiple 10 --judge 10
PaperDrill.exe --bank 题库.xlsx --progress-dir 目录 --exam A --exam-ratio 0.9 --log 结果.txt
PaperDrill.exe --make-template 题库模板.xlsx
PaperDrill.exe --gui-selftest --bank 题库.xlsx --out 临时进度目录 --result 结果.json
PaperDrill.exe --qt-selftest  --bank 题库.xlsx --out 临时进度目录 --result 结果.json
```

## 已知边界

- 多选题不设部分分；未答题按错误计分（成绩页单列）；
- 题干或选项被修改过的题目视为新题，进度从零开始；
- 未交卷的考试答案不保留（练习作答则即时保存）；
- 换机器携带进度需自行拷贝 `%APPDATA%\PaperDrill\progress\` 目录；
- **两套界面不同时演进**：Qt 界面是功能主线；tkinter 界面仅在 PySide6 不可用时兜底
  （能练、能考、能恢复进度，但观感为旧版）。

---

本项目由 DeepSeek + DeepSeek Harness 开发。
