# 刷题匠 PaperDrill

> 题库刷题练习 + 模拟考试桌面工具 ｜ **AI 开发**（DeepSeek）｜ Windows 单文件 exe，免安装、免联网、可直接分享

**当前版本：v1.2.1** ｜ 自动化测试 **154 项**（见 `tests/`，推送时由 CI 全量执行）

> ⚠️ **本项目由 AI 开发**：源码、文档、测试与构建脚本均由 AI 编写，人类提出需求并验收。
> 详见 **[AI-DEVELOPED.md](AI-DEVELOPED.md)**。

---

## 功能一览

- 三种题型：单选 / 多选 / 判断
- 题库格式：Excel、CSV、TXT、JSON、**Word（表格型 / 段落文本型）**、**PDF（文本型）**
- 实时判题：单选/判断点选即判，多选提交判；显示正确答案与解析
- 按题型练习、错题重练、只练未做、随机/顺序练习
- 自定义蓝图生成试卷（题量 × 题型占比），一轮覆盖全部题目，末卷自动补题
- 模拟考试：作答期间不提示对错，交卷一次性评分（含各题型得分明细与逐题明细）
- 进度自动保留：题目指纹定位，题库增删/改名自动继承进度
- 快捷键：`1~8` 选答案、`Enter` 下一题、`←/→` 翻题、`F9` 交卷

## 快速开始

### 方式一：直接运行 exe（推荐给使用者）

1. 到本仓库 **Releases** 下载 `PaperDrill.exe`（或从 **Actions** 下载最新构建产物）；
2. 双击运行，点「导入题库…」选择题库文件；
3. 说明文档见 [`使用说明.md`](使用说明.md)。

> exe 为 Windows 10/11 x64 单文件程序，**不需要安装 Python**。

### 方式二：从源码运行

```bash
python -m venv .venv
.venv\\Scripts\\activate          # Windows
pip install -r requirements.txt

# 生成一份合成示例题库（不会联网，也不含任何真实单位数据）
python tools/make_samples.py

set PYTHONPATH=src
python -m paperdrill --bank samples\\示例题库.xlsx
```

### 方式三：自行打包单文件 exe

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1
# 产物：dist\\PaperDrill.exe
```

## 题库格式

支持 `.xlsx` / `.xlsm` / `.csv` / `.txt` / `.json` / `.docx` / `.pdf`：

| 格式 | 说明 |
|---|---|
| Excel / CSV / TXT | 列头：`题型 | 题目标题 | 选项A…选项H | 解析 | 答案`；列名可用同义词，**列顺序不限、首行可以是标题、列头可写在第 20 行内** |
| Word | **表格型**（列头同 Excel）或**段落文本型**（题干/选项/答案分行，答案可写在题干括号里如 `（C）`、`（  BCE ）`、`（√）`） |
| PDF | 读取文本层（扫描件不支持）；先按段落解析，再用「多空格分列」兜底 |
| JSON | 中文键（`题型`/`题目标题`/`选项A`…）或英文键（`type`/`stem`/`optionA`…）均可 |

- 多选答案写字母组合（`ABCD`）；选项顺序不可打乱的题在答案后加「（定）」（如 `BC（定）`）；
- 无法解析的行不会进入题库，但会给出「行号 + 原因 + 题干片段」。

示例题库由 [`tools/make_samples.py`](tools/make_samples.py) 生成（合成内容，可商用参考）：
`samples/` 放文本格式示例，`fixtures/` 放集成测试夹具（Word 各版式 + PDF）。

## 文档

| 文档 |
|---|
| [需求规格说明书](docs/01-需求规格说明书.md) |
| [概要设计说明书](docs/02-概要设计说明书.md) |
| [测试报告](docs/03-测试报告.md) |
| [缺陷分析：Enter 快捷键](docs/04-快捷键缺陷分析与修复.md) |
| [缺陷分析：重做已作答题目](docs/05-重做已作答题目缺陷分析与修复.md) |
| [Word / PDF 题库导入说明](docs/06-Word与PDF题库导入说明.md) |

## 测试与质量

```bash
python tools/make_samples.py            # 生成合成题库与夹具
python -m unittest discover -s tests    # 全量自动化测试
```

- 测试覆盖：解析（含 Word/PDF 各版式与异常输入）、组卷覆盖算法、打乱与「（定）」保护、
  进度存储与继承、界面流程（真实 Tk 对象无头自检）、CLI 与 exe 端到端；
- 缺陷修复过程如实记录在 `docs/` 的缺陷分析报告中（含复现证据与根因）。

## AI 开发说明

| 项 | 说明 |
|---|---|
| 开发方式 | AI 自主开发（需求 → 规格 → 设计 → 测试先行 → 实现 → 打包 → 验证） |
| 模型 | DeepSeek（DeepSeek Harness 环境） |
| 人类角色 | 需求定义、方案取舍确认、结果验收 |
| 声明 | 见 [AI-DEVELOPED.md](AI-DEVELOPED.md) |

## 许可

[MIT](LICENSE) —— 可自由使用、修改、分发（保留版权声明）。软件按"现状"提供，不提供担保。

## 免责声明

本项目为通用题库工具，不针对任何特定单位或考试；仓库内示例题目均为**合成的通用示例**。
使用者应自行确保导入的题库内容合法合规。
