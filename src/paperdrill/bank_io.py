# -*- coding: utf-8 -*-
"""题库读写：支持 xlsx/xlsm、csv、txt、json、docx、pdf。

设计要点
--------
* 表格型数据源（Excel/CSV/TXT/JSON、Word 表格、PDF 表格）走 ``rows_to_questions``：
  列头同义词识别 + 位置回退，兼容用户自行整理过的表格；
* 段落型数据源（Word 段落、PDF 文本）走 ``lines_to_questions``：
  识别章节标题（题型）、题干、选项、答案行、解析行，答案可嵌在题干括号里；
* 逐行校验，坏行不进入题库，但完整记录原因供界面提示；
* 全部读入为 ``list[Question]``，交给领域层处理。
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .models import (
    OPTION_LABELS,
    AnswerParseError,
    QType,
    Question,
    normalize_text,
    parse_answer,
    parse_qtype,
)

__all__ = [
    "BankIssue", "BankLoadResult", "TextLine", "load_bank", "questions_to_rows",
    "export_questions_to_xlsx", "write_template_xlsx", "build_sample_questions",
    "bank_stats", "SUPPORTED_SUFFIXES", "lines_to_questions",
    "TEXT_SUFFIXES", "WORD_SUFFIXES", "PDF_SUFFIXES",
]

TEXT_SUFFIXES = (".csv", ".txt")
WORD_SUFFIXES = (".docx", ".docm")
PDF_SUFFIXES = (".pdf",)
SUPPORTED_SUFFIXES = (".xlsx", ".xlsm") + TEXT_SUFFIXES + (".json",) + WORD_SUFFIXES + PDF_SUFFIXES

# ---------------------------------------------------------------- 列头同义词
_HEADER_SYNONYMS: dict[str, list[str]] = {
    "type": ["题型", "题目类型", "类型", "试题类型", "分类", "题目种类", "试题分类",
             "type", "kind", "category"],
    "stem": ["题目标题", "题目", "题干", "试题", "问题", "题目内容", "试题内容", "试题题目",
             "题干内容", "题干题目", "题目描述", "题目正文", "试题题干",
             "stem", "question", "title", "questiontext", "description"],
    "analysis": ["解析", "答案解析", "试题解析", "题目解析", "说明", "分析", "参考答案解析",
                 "备注", "依据", "来源", "知识点", "analysis", "explain", "explanation"],
    "answer": ["答案", "正确答案", "参考答案", "标准答案", "正确选项", "答案选项",
               "answer", "key", "correctanswer"],
}
_OPTION_HEADER_RE = re.compile(r"^(?:选项)?\s*([A-Ha-h])\s*(?:选项)?$")
_HEADER_SCAN_ROWS = 20                                   # 列头行扫描范围（原为 5 行）


@dataclass
class BankIssue:
    """一条无法导入的记录。"""

    row: int
    reason: str
    raw: str = ""

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return f"第 {self.row} 行：{self.reason}"


@dataclass
class BankLoadResult:
    """题库加载结果。"""

    questions: list[Question] = field(default_factory=list)
    issues: list[BankIssue] = field(default_factory=list)
    source: str = ""
    sheet: str = ""
    header: list[str] = field(default_factory=list)
    column_map: dict[str, object] = field(default_factory=dict)

    @property
    def ok_count(self) -> int:
        return len(self.questions)

    def type_counts(self) -> dict[QType, int]:
        counts = {QType.SINGLE: 0, QType.MULTIPLE: 0, QType.JUDGE: 0}
        for q in self.questions:
            counts[q.qtype] += 1
        return counts


# ---------------------------------------------------------------- 行数据读取
def _read_xlsx(path: Path) -> tuple[str, list[list[str]]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        candidates: list[tuple[int, int, int, str, list[list[str]]]] = []
        for order, ws in enumerate(wb.worksheets):
            rows: list[list[str]] = []
            for row in ws.iter_rows(values_only=True):
                rows.append([normalize_text(c) for c in row])
            if not rows:
                continue
            header_idx, _, _ = _detect_header(rows)
            # 优先级：能识别列头 > 行数多 > 工作表靠前
            candidates.append((1 if header_idx >= 0 else 0, len(rows), -order, ws.title, rows))
        if not candidates:
            return "", []
        best = max(candidates, key=lambda t: (t[0], t[1], t[2]))
        return best[3], best[4]
    finally:
        wb.close()


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")  # pragma: no cover


def _sniff_delimiter(text: str) -> str:
    head = "\n".join(text.splitlines()[:5])
    for delim in ("\t", "|", ";", ",", "，"):
        if head.count(delim) >= 1:
            return "," if delim == "，" else delim
    try:
        return csv.Sniffer().sniff(text[:4096]).delimiter
    except Exception:
        return ","


def _read_delimited(path: Path) -> list[list[str]]:
    text = _decode(path.read_bytes())
    if not text.strip():
        return []
    delim = _sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    return [[normalize_text(c) for c in row] for row in reader]


def _read_json(path: Path) -> list[list[str]]:
    """JSON 支持 {"questions":[...]} 或直接数组；元素为对象。"""
    data = json.loads(_decode(path.read_bytes()) or "[]")
    if isinstance(data, dict):
        for key in ("questions", "data", "items", "list", "题目", "题库"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            raise ValueError("JSON 结构无法识别：未找到题目数组（questions/data/items）")
    if not isinstance(data, list):
        raise ValueError("JSON 顶层必须是数组或包含 questions 数组的对象")

    def pick(obj: dict, names: Sequence[str], default=""):
        for n in names:
            if n in obj and obj[n] not in (None, ""):
                return obj[n]
        lowered = {str(k).lower(): v for k, v in obj.items()}
        for n in names:
            if n.lower() in lowered and lowered[n.lower()] not in (None, ""):
                return lowered[n.lower()]
        return default

    rows: list[list[str]] = []
    for obj in data:
        if not isinstance(obj, dict):
            rows.append([normalize_text(obj)])
            continue
        opts = pick(obj, ["options", "选项", "选项列表", "choices"], [])
        if isinstance(opts, str):
            opts = re.split(r"[\n\r]+", opts)
        if isinstance(opts, dict):
            opts = [opts[k] for k in sorted(opts)]
        opt_texts = [normalize_text(o) for o in (opts or [])]
        # 允许 A/B/C/D 与 选项A 两种键
        for letter in OPTION_LABELS:
            v = pick(obj, [f"选项{letter}", f"option{letter}", letter, letter.lower()], "")
            if v not in ("", None):
                while len(opt_texts) <= OPTION_LABELS.index(letter):
                    opt_texts.append("")
                opt_texts[OPTION_LABELS.index(letter)] = normalize_text(v)
        while opt_texts and not opt_texts[-1]:
            opt_texts.pop()
        opt_texts = (opt_texts + [""] * 8)[:8]
        rows.append([
            normalize_text(pick(obj, ["type", "题型", "题目类型", "类型", "试题类型"], "")),
            normalize_text(pick(obj, ["stem", "question", "题干", "题目", "title",
                                      "题目标题", "题目内容", "试题内容", "试题题目"], "")),
            *opt_texts,
            normalize_text(pick(obj, ["analysis", "解析", "说明", "答案解析", "依据", "来源"], "")),
            normalize_text(pick(obj, ["answer", "答案", "正确答案", "参考答案", "标准答案", "key"], "")),
        ])
    return rows


# ---------------------------------------------------------------- 列映射
def _header_token(cell: object) -> str:
    """列头比对用的归一化文本：全半角统一、去空白与换行。"""
    return normalize_text(cell).lower().replace(" ", "").replace("\n", "").replace("\t", "")


def _option_letter_of_header(cell: object) -> "str | None":
    """把列头单元格解析为选项字母 A–H；不是选项列返回 None。

    兼容 `选项A` / `A选项` / `选项 A` / `A` / `A、` / `选项（A）` / `选项1`
    / `optionA` / `opt A` 等写法。
    """
    token = _header_token(cell)
    if not token:
        return None
    for affix in ("选项", "options", "option", "opt"):
        token = token.replace(affix, "")
    token = token.strip("()[]（）第项列：:、,，.")
    if len(token) != 1:
        return None
    if token in "abcdefgh":
        return token.upper()
    if token in "12345678":
        return "ABCDEFGH"[int(token) - 1]
    return None


def _detect_header(rows: list[list[str]]) -> tuple[int, dict[str, object], list[str]]:
    """在前若干行中寻找列头行，返回 (行索引, 列映射, 原始列头)。

    识别条件：该行含题干同义词，且**至少有 2 个选项字母列**，或**有 1 个"选项"合并列**
    （内容形如 `A.甲 B.乙`，后续会自动展开）。
    """
    for i, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        mapping: dict[str, object] = {}
        opt_cols: dict[int, str] = {}
        combo_col: "int | None" = None
        for j, cell in enumerate(row):
            token = _header_token(cell)
            if not token:
                continue
            matched = False
            for key, names in _HEADER_SYNONYMS.items():
                if token in [_header_token(n) for n in names]:
                    mapping.setdefault(key, j)
                    matched = True
                    break
            if matched:
                continue
            if token in _COMBINED_OPTION_HEADERS:
                if combo_col is None:
                    combo_col = j
                continue
            letter = _option_letter_of_header(cell)
            if letter:
                opt_cols[j] = letter
        if "stem" not in mapping:
            continue
        # 有 2 个以上选项列、或有 1 个「选项」合并列、或至少有题型/答案列 → 认为是列头行
        if (len(opt_cols) >= 2 or (combo_col is not None and not opt_cols)
                or "type" in mapping or "answer" in mapping):
            mapping["options"] = opt_cols
            if combo_col is not None:
                mapping["combined_option_col"] = combo_col
            mapping["header_row"] = i
            return i, mapping, list(row)
    return -1, {}, []


def _positional_map(width: int) -> "dict[str, object] | None":
    """无列头时的位置回退策略；**仅为与常见模板吻合的列数**回退。

    12 列（标准全宽）、8 列（题型/题干/A–D/解析/答案）、3 列（题型/题干/答案）以外
    一律返回 ``None``：宁可明确报错，也不要按位置猜错列（例如把 D 选项当成答案）。
    """
    if width >= 12:
        return {"type": 0, "stem": 1, "options": {j: OPTION_LABELS[j - 2] for j in range(2, 10)},
                "analysis": 10, "answer": 11}
    if width == 8:
        return {"type": 0, "stem": 1, "options": {j: OPTION_LABELS[j - 2] for j in range(2, 6)},
                "analysis": 6, "answer": 7}
    if width == 3:
        return {"type": 0, "stem": 1, "options": {}, "analysis": -1, "answer": 2}
    return None


def _cell(row: Sequence[str], idx: object) -> str:
    if idx is None:
        return ""
    try:
        i = int(idx)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if i < 0 or i >= len(row):
        return ""
    return normalize_text(row[i])


# ---------------------------------------------------------------- 主流程
def _infer_qtype(answer: str, options: list[str]) -> "QType | None":
    """缺「题型」列时由答案形态推断题型（与段落解析器同一套规则）。"""
    token = normalize_text(answer)
    if not token:
        return None
    if _judge_from_token(token) is not None and (not options or len(options) < 2):
        return QType.JUDGE
    letters = _letters_from_token(token)
    if len(letters) >= 2:
        return QType.MULTIPLE
    if len(letters) == 1:
        return QType.JUDGE if not options else QType.SINGLE
    if _judge_from_token(token) is not None:
        return QType.JUDGE
    return None


def rows_to_questions(rows: list[list[str]], *, start_row: int = 1
                      ) -> tuple[list[Question], list[BankIssue], list[str], dict]:
    """把二维表行转换为 Question 列表。"""
    issues: list[BankIssue] = []
    questions: list[Question] = []
    if not rows:
        return questions, issues, [], {}

    header_idx, cmap, header = _detect_header(rows)
    if header_idx >= 0 and cmap.get("combined_option_col") is not None:
        # 「选项」在一列里（如 `A.甲 B.乙 C.丙 D.丁`）→ 展开成 选项A…选项H 再重新识别
        expanded = _expand_combined_options(rows)
        if expanded is not rows:
            header_idx, cmap, header = _detect_header(expanded)
            rows = expanded

    if header_idx >= 0:
        data_rows = rows[header_idx + 1:]
        first_data_row = start_row + header_idx + 1
        width = max((len(r) for r in rows), default=0)
    else:
        data_rows = rows
        first_data_row = start_row
        width = max((len(r) for r in rows), default=0)
        cmap = _positional_map(width)
        if cmap is None:
            raise ValueError(
                f"未找到可识别的列头行（需包含「题干」以及至少 2 个「选项A…」列，或 1 个「选项」合并列）；"
                f"当前表格 {width} 列且无法按位置安全推断。请在第一行补上列头，例如："
                "题型 | 题目标题 | 选项A | 选项B | 选项C | 选项D | 解析 | 答案")
        header = []

    opt_cols: dict[int, str] = dict(cmap.get("options", {}))  # type: ignore[arg-type]

    running = 0
    for offset, row in enumerate(data_rows):
        row_no = first_data_row + offset
        if not any(normalize_text(c) for c in row):
            continue
        raw_preview = " | ".join(normalize_text(c) for c in row[:4])[:120]

        texts: list[tuple[str, str]] = []
        for col, letter in sorted(opt_cols.items(), key=lambda kv: kv[1]):
            text = _cell(row, col)
            texts.append((letter, text))
        texts.sort(key=lambda kv: kv[0])
        while texts and not texts[-1][1]:
            texts.pop()
        options_preview = [t for _, t in texts]

        raw_type = _cell(row, cmap.get("type"))
        raw_answer = _cell(row, cmap.get("answer"))
        qtype = parse_qtype(raw_type)
        if qtype is None:
            if raw_type.strip():
                issues.append(BankIssue(row_no, f"题型无法识别：{raw_type!r}", raw_preview))
                continue
            qtype = _infer_qtype(raw_answer, options_preview)      # 缺题型列 → 由答案推断
            if qtype is None:
                issues.append(BankIssue(
                    row_no, "缺少「题型」列，且无法由答案推断题型（请补题型列或填答案）", raw_preview))
                continue

        stem = _cell(row, cmap.get("stem"))
        if not stem:
            issues.append(BankIssue(row_no, "题干为空", raw_preview))
            continue

        options = options_preview
        if any(not t for t in options):
            issues.append(BankIssue(row_no, "选项不连续（中间存在空列），请整理后重新导入", raw_preview))
            continue
        if qtype is not QType.JUDGE and len(options) < 2:
            issues.append(BankIssue(
                row_no, f"{qtype.value}缺少选项（本题只识别到 {len(options)} 个选项列），"
                        "请检查列头是否写成了「选项A / 选项B …」或使用单列「选项」列", raw_preview))
            continue

        if not raw_answer and qtype is QType.JUDGE:
            issues.append(BankIssue(row_no, "缺少答案", raw_preview))
            continue
        try:
            letters, judge, fixed = parse_answer(qtype, raw_answer, max(len(options), 1))
        except AnswerParseError as exc:
            issues.append(BankIssue(row_no, str(exc), raw_preview))
            continue

        running += 1
        q = Question(
            qid=f"{qtype.key}-{running:04d}",
            qtype=qtype,
            stem=stem,
            options=options,
            answer_letters=letters,
            judge_answer=judge,
            fixed_order=fixed,
            analysis=_cell(row, cmap.get("analysis")),
            src_row=row_no,
        )
        problems = q.validate()
        if problems:
            issues.append(BankIssue(row_no, "；".join(problems), raw_preview))
            continue
        questions.append(q)

    return questions, issues, header, dict(cmap.items())


# ================================================================ 段落文本解析
# 用于 Word 段落型题库与 PDF 文本型题库：逐行状态机识别章节/题干/选项/答案/解析。

_FW_LETTERS = str.maketrans("ＡＢＣＤＥＦＧＨａｂｃｄｅｆｇｈ", "ABCDEFGHabcdefgh")
_FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

_LETTER_CLS = "A-Ha-hＡ-Ｈａ-ｈ"

_SECTION_RE = re.compile(
    r"^\s*(?:第\s*[一二三四五六七八九十0-9０-９]+\s*部分\s*[:：]?|[一二三四五六七八九十]+\s*[、.．])"
    r"\s*(.*?)\s*$"
)
_QNUM_RE = re.compile(r"^\s*([0-9０-９]{1,3})\s*(?:[、．)）]\s*|\.\s*(?![0-9０-９]))(\S.*)$")
_STEM_PREFIX_RE = re.compile(r"^\s*题\s*干\s*[:：]\s*(.*)$")
_ANS_RE = re.compile(
    r"^\s*(?:[【\[（(]\s*)?(?:参考答案|正确答案|标准答案|答案)\s*(?:[】\]）)])?\s*[:：]?\s*(\S.*)$"
)
_ANA_RE = re.compile(r"^\s*(?:解析|来源|依据|说明|知识点|出处|文件依据)\s*[:：]\s*(.*)$")
_OPT_MARK_RE = re.compile(rf"([{_LETTER_CLS}])\s*[.．、,，:：]\s*")
_OPT_START_RE = re.compile(rf"^\s*[{_LETTER_CLS}]\s*[.．、,，:：]")
_LETTER_CHARS = "ABCDEFGHabcdefghＡＢＣＤＥＦＧＨａｂｃｄｅｆｇｈ"
_CJK_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF))
_PUNCT_BEFORE_OPTION = "，。；：、）)】］>"
_BRACKET_RE = re.compile(r"[（(]\s*([^（）()]{0,16}?)\s*[）)]")
_ANSWER_TOKEN_RE = re.compile(
    rf"^(?:[{_LETTER_CLS}]{{1,8}}(?:\s*[、,，/]\s*[{_LETTER_CLS}]{{1,8}})*"
    r"|[√✓×✗对错]|正确|错误|是|否|T|F|True|False)$",
    re.IGNORECASE,
)
_GLUE_RE = re.compile(r"(?<=\S)\s*([0-9０-９]{1,3})\s*(?:[、．)）]\s*|\.\s*(?![0-9０-９]))(\S.*)$")

_SECTION_TYPES: list[tuple[tuple[str, ...], QType]] = [
    (("单项选择", "单选"), QType.SINGLE),
    (("多项选择", "多选", "不定项"), QType.MULTIPLE),
    (("判断题", "判断", "是非", "对错"), QType.JUDGE),
]
_SECTION_SKIP = ("案例", "主观", "简答", "问答", "论述", "计算", "填空", "绘图", "实操", "名词解释")


@dataclass
class TextLine:
    """段落文本中的一行（Word 段落 / 软换行 / PDF 文本行）。"""

    text: str
    is_heading: bool = False
    source: int = 0


def _letter(ch: str) -> str:
    return ch.translate(_FW_LETTERS).upper()


def _digits(text: str) -> str:
    return text.translate(_FW_DIGITS)


def _classify_section(title: str) -> "QType | str | None":
    """章节标题 → 题型；``"skip"`` 表示该章节不收录（主观题等）。"""
    t = title.strip()
    for key in _SECTION_SKIP:
        if key in t:
            return "skip"
    for keys, qtype in _SECTION_TYPES:
        for key in keys:
            if key in t:
                return qtype
    return None


def _has_section_keyword(title: str) -> bool:
    t = title.strip()
    if any(k in t for k in _SECTION_SKIP):
        return True
    return any(k in t for keys, _ in _SECTION_TYPES for k in keys)


def _judge_from_token(token: str) -> "bool | None":
    """判断题答案 token → True/False；不是判断型答案则返回 None。"""
    t = _digits(token).strip().upper()
    if t in ("√", "✓", "对", "正确", "是", "T", "TRUE", "A", "1"):
        return True
    if t in ("×", "✗", "x", "X", "错", "错误", "否", "F", "FALSE", "B", "0"):
        return False
    return None


def _letters_from_token(token: str) -> list[str]:
    out: list[str] = []
    for ch in token:
        letter = _letter(ch) if ch in "ABCDEFGHabcdefghＡＢＣＤＥＦＧＨａｂｃｄｅｆｇｈ" else ""
        if letter and letter not in out:
            out.append(letter)
    return sorted(out)


_JUDGE_OPTION_WORDS = ("正确", "错误", "对", "错", "是", "否", "√", "×", "✓", "✗")


def _options_look_like_judge(options: dict[str, str]) -> bool:
    """选项本身是否是"正确 / 错误"两类（据此判断字母答案是不是判断题答案）。"""
    texts = [normalize_text(t) for t in options.values() if t is not None]
    if len(texts) != 2:
        return False
    return all(any(w in t for w in _JUDGE_OPTION_WORDS) for t in texts)


def _extract_embedded_answer(stem: str) -> tuple["str | None", str]:
    """从题干括号里提取答案，并把答案抹成作答空位。

    只处理"像答案"的括号内容（``（C）``/``（ABCD）``/``（  BCE ）``/``（√）``），
    像 ``（含）`` 这种普通括号原样保留；空括号 ``（  ）`` 也不动。
    返回 ``(答案token 或 None, 处理后的题干)``。
    """
    found: "str | None" = None

    def _replace(m: re.Match) -> str:
        nonlocal found
        token = m.group(1).strip()
        if not token or not _ANSWER_TOKEN_RE.match(token):
            return m.group(0)
        if found is None:
            found = token
        return "（　　）"

    cleaned = _BRACKET_RE.sub(_replace, stem)
    return found, cleaned


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _CJK_RANGES)


def _is_latin(ch: str) -> bool:
    return ("A" <= ch.upper() <= "Z") or ("0" <= ch <= "9")


def _iter_option_marks(text: str) -> list[tuple[int, str, int]]:
    """扫描一行中所有"像选项标记"的位置。

    返回 ``[(标记起始下标, 选项字母, 选项文本起始下标)]``。

    识别三种常见写法：
    * ``A.内容`` / ``A．内容`` / ``A、内容``（带分隔符）
    * ``C  2.5m``（字母 + 空格，无分隔符）
    * ``A明确内容``（字母后直接接中文的写法）

    同时排除 ``ABC`` 这类正文里的拉丁字母串。
    """
    out: list[tuple[int, str, int]] = []
    n = len(text)
    for i, ch in enumerate(text):
        if ch not in _LETTER_CHARS:
            continue
        letter = _letter(ch)
        prev = text[i - 1] if i else ""
        if i and not (prev.isspace() or prev in _PUNCT_BEFORE_OPTION or _is_cjk(prev)):
            continue
        j = i + 1
        while j < n and text[j] in " \u3000\t":
            j += 1
        if j < n and text[j] in ".．、,，:：":
            j += 1
            while j < n and text[j] in " \u3000\t":
                j += 1
            if j < n:
                out.append((i, letter, j))
            continue
        if j < n and text[j] in ")）":
            out.append((i, letter, j + 1))
            continue
        if j < n and not ("A" <= text[j].upper() <= "Z"):
            out.append((i, letter, j))
    return out


def _is_option_line(text: str) -> bool:
    if len(text) > 400:
        return False
    marks = _iter_option_marks(text)
    if not marks:
        return False
    return marks[0][0] == 0 or len(marks) >= 2


def _split_options(text: str) -> tuple[list[tuple[str, str]], "str | None"]:
    """把一行切成 ``[(字母, 选项文本)]``，并返回尾部粘连的下一题内容。"""
    marks = _iter_option_marks(text)
    if not marks:
        return [], None

    segs: list[tuple[str, str]] = []
    for i, (_start, letter, content_start) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        segs.append((letter, text[content_start:end].strip()))

    leftover: "str | None" = None
    letter, last = segs[-1]
    glue = _GLUE_RE.search(last)
    if glue and len(glue.group(2)) >= 2:                # 尾部粘连了下一题题干（至少 2 个字符才切）
        segs[-1] = (letter, last[: glue.start()].strip())
        leftover = f"{_digits(glue.group(1))}、{glue.group(2)}"
    return [(lab, txt) for lab, txt in segs if txt], leftover


def _decide_qtype(section: "QType | str | None", answer_token: str,
                  options: dict[str, str]) -> "QType | None":
    """题型判定：章节优先，答案形态兜底；单选章节出现多字母答案时容错为多选。

    注意：字母答案 ``A``/``B`` 既可能是单选选项，也可能是判断题的"正确/错误"，
    因此**只有在没有选项、或选项本身就是"正确/错误"两类**时才按判断题处理，
    否则 ``（B）`` 这类单选答案会被误判成判断题并丢掉全部选项。
    """
    letters = _letters_from_token(answer_token)
    judge = _judge_from_token(answer_token) if answer_token else None
    if section is QType.JUDGE:
        return QType.JUDGE
    judge_like = (not options) or _options_look_like_judge(options)
    if judge is not None and judge_like:
        return QType.JUDGE
    if section is QType.MULTIPLE:
        return QType.MULTIPLE
    if section is QType.SINGLE:
        return QType.MULTIPLE if len(letters) >= 2 else QType.SINGLE
    if len(letters) >= 2:
        return QType.MULTIPLE
    if len(letters) == 1:
        return QType.SINGLE
    if options:
        return QType.SINGLE
    return None


def lines_to_questions(lines: Sequence[TextLine], *, start_line: int = 1
                       ) -> tuple[list[Question], list[BankIssue], dict]:
    """解析段落型题库（Word 段落 / PDF 文本）。

    返回 ``(questions, issues, meta)``；``meta`` 含 ``warnings`` 与计数信息。
    """
    buf: "deque[TextLine]" = deque(lines)
    questions: list[Question] = []
    issues: list[BankIssue] = []
    warnings: list[str] = []
    counter = 0
    section: "QType | str | None" = None
    cur: "dict | None" = None
    row_no = start_line - 1

    def flush() -> None:
        nonlocal cur, counter
        if cur is None:
            return
        data, cur = cur, None
        stem = re.sub(r"\s+", " ", "".join(data["stem"])).strip()
        if not stem:
            return
        answer_token = data["answer"].strip()
        if not answer_token:
            token, cleaned = _extract_embedded_answer(stem)
            if token:
                answer_token = token
                stem = re.sub(r"\s+", " ", cleaned).strip()
        sec = data["section"]
        if sec == "skip":
            return
        options = data["options"]
        qtype = _decide_qtype(sec, answer_token, options)
        if qtype is None:
            issues.append(BankIssue(data["row"], "未找到答案（题干括号为空且无答案行）",
                                    stem[:120]))
            return
        text_letters = _letters_from_token(answer_token)
        need_options = qtype is not QType.JUDGE
        if need_options and len(options) < 2:
            issues.append(BankIssue(data["row"], f"选项少于 2 个（实际 {len(options)}）", stem[:120]))
            return
        if not answer_token:
            issues.append(BankIssue(data["row"], "缺少答案", stem[:120]))
            return
        # 单选章节里出现了多字母答案 → 容错为多选并提示
        if sec is QType.SINGLE and len(text_letters) >= 2:
            warnings.append(f"第 {data['row']} 行：章节标注为单选题，但答案有 {len(text_letters)} 个字母，"
                            f"已按多选题收录。")
        try:
            letters, judge_value, fixed = parse_answer(
                qtype, answer_token, max(len(options), 1))
        except AnswerParseError as exc:
            issues.append(BankIssue(data["row"], str(exc), stem[:120]))
            return
        counter += 1
        ordered = sorted(options.items())
        q = Question(
            qid=f"{qtype.key}-{counter:04d}",
            qtype=qtype,
            stem=stem,
            options=[text for _, text in ordered] if need_options else [],
            answer_letters=letters,
            judge_answer=judge_value,
            fixed_order=fixed,
            analysis=" ".join(a for a in data["analysis"] if a).strip(),
            src_row=data["row"],
        )
        problems = q.validate()
        if problems:
            issues.append(BankIssue(data["row"], "；".join(problems), stem[:120]))
            counter -= 1
            return
        questions.append(q)

    while buf:
        ln = buf.popleft()
        text = (ln.text or "").strip()
        if not text:
            continue
        row_no = ln.source or (row_no + 1)

        # 1) 章节标题（题型切换）
        m = _SECTION_RE.match(text)
        if m and _has_section_keyword(m.group(1)):
            flush()
            section = _classify_section(m.group(1))
            continue

        # 2) 答案行
        m = _ANS_RE.match(text)
        if m:
            if cur is not None:
                cur["answer"] = m.group(1)
            continue

        # 3) 解析/来源行
        m = _ANA_RE.match(text)
        if m:
            if cur is not None:
                cur["analysis"].append(m.group(1))
            continue

        # 4) 新题起始
        m = _QNUM_RE.match(text)
        if m:
            flush()
            cur = {"stem": [m.group(2)], "options": {}, "answer": "", "analysis": [],
                   "row": row_no, "section": section}
            continue
        m = _STEM_PREFIX_RE.match(text)
        if m:
            flush()
            cur = {"stem": [m.group(1)], "options": {}, "answer": "", "analysis": [],
                   "row": row_no, "section": section}
            continue

        # 5) 选项行
        if _is_option_line(text) and cur is not None:
            segs, leftover = _split_options(text)
            for letter, opt in segs:
                if letter not in cur["options"]:
                    cur["options"][letter] = opt
            if leftover:
                buf.appendleft(TextLine(leftover, source=row_no))
            continue

        # 6) 续行：多行题干 / 折行的选项 / 说明
        if cur is None:
            continue
        if not cur["options"]:
            cur["stem"].append(text)
        elif not cur["answer"] and not cur["analysis"] and cur["options"]:
            last = sorted(cur["options"])[-1]           # 选项折行：接到最后一个选项
            cur["options"][last] += text
        else:
            cur["analysis"].append(text)

    flush()

    meta = {"warnings": warnings, "total_lines": len(lines),
            "skipped_sections": sum(1 for q in [] ) if False else 0}
    return questions, issues, meta


# ---------------------------------------------------------------- Word / PDF
def _read_docx(path: Path) -> tuple[list[list[list[str]]], list[TextLine]]:
    """读取 Word：返回 (若干表格, 段落行)。"""
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - 仅在缺依赖时发生
        raise ValueError("缺少 python-docx，无法读取 Word 题库，请重新安装或改用 Excel。") from exc

    try:
        doc = Document(str(path))
    except Exception as exc:
        raise ValueError(f"无法打开 Word 文件（可能已损坏或为 .doc 旧格式）：{exc}") from exc

    tables: list[list[list[str]]] = []
    for table in doc.tables:
        rows: list[list[str]] = []
        for row in table.rows:
            cells: list[str] = []
            seen: set[int] = set()
            for cell in row.cells:                      # 合并单元格会重复出现
                key = id(cell._tc)
                if key in seen:
                    continue
                seen.add(key)
                cells.append(normalize_text(cell.text))
            rows.append(cells)
        if rows:
            tables.append(rows)

    lines: list[TextLine] = []
    for idx, para in enumerate(doc.paragraphs, start=1):
        raw = para.text or ""
        if not raw.strip():
            continue
        style_name = ""
        try:
            style_name = str(para.style.name or "")
        except Exception:
            style_name = ""
        is_heading = ("heading" in style_name.lower()) or ("标题" in style_name)
        for part in raw.split("\n"):
            part = part.strip()
            if part:
                lines.append(TextLine(part, is_heading=is_heading, source=idx))
    return tables, lines


def _read_pdf(path: Path) -> list[TextLine]:
    """读取 PDF 文本行；无文字层时给出可读提示。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ValueError("缺少 pypdf，无法读取 PDF 题库，请重新安装或改用 Word/Excel。") from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise ValueError(f"无法打开 PDF 文件（可能已损坏或格式不受支持）：{exc}") from exc

    if getattr(reader, "is_encrypted", False):
        try:
            if reader.decrypt("") == 0:
                raise ValueError("PDF 已加密")
        except Exception as exc:
            raise ValueError("PDF 已加密，无法读取；请先解除密码保护或改用 Word/Excel 题库。") from exc

    lines: list[TextLine] = []
    try:
        pages = list(reader.pages)
    except Exception as exc:
        raise ValueError(f"无法解析 PDF 页面：{exc}") from exc

    for pno, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        for raw in text.splitlines():
            raw = raw.strip()
            if raw:
                lines.append(TextLine(raw, source=pno))

    if not lines:
        raise ValueError("未能从 PDF 中提取到任何文字：该文件很可能是扫描件（图片），"
                         "请改用文本版 PDF，或提供 Word/Excel 题库。")
    return lines


def _pdf_lines_to_rows(lines: Sequence[TextLine]) -> list[list[str]]:
    """PDF 表格化兜底：按连续多空格分列。"""
    rows: list[list[str]] = []
    for ln in lines:
        cells = [c.strip() for c in re.split(r"\s{2,}|\t", ln.text) if c.strip()]
        if len(cells) >= 2:
            rows.append(cells)
    return rows


_COMBINED_OPTION_HEADERS = {"选项", "选项内容", "备选项", "答案选项", "可选项", "选项列表",
                            "options", "option", "选项（一行）"}


def _expand_combined_options(rows: list[list[str]]) -> list[list[str]]:
    """把"所有选项挤在一列"的表格展开成 选项A…选项H 多列。

    表头不一定在第 1 行（上方可能有标题/空行），因此先用与列头识别相同的规则定位表头行。
    """
    if not rows:
        return rows

    stem_tokens = {_header_token(n) for n in _HEADER_SYNONYMS["stem"]}
    header_idx = -1
    combo = None
    for i, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        tokens = [_header_token(c) for c in row]
        if not any(t in _COMBINED_OPTION_HEADERS for t in tokens):
            continue
        if not any(t in stem_tokens for t in tokens if t):
            continue
        header_idx = i
        combo = next(j for j, t in enumerate(tokens) if t in _COMBINED_OPTION_HEADERS)
        break
    if header_idx < 0 or combo is None:
        return rows

    header = rows[header_idx]
    if any(_option_letter_of_header(h) for h in header if h):
        return rows                                        # 已有 A–H 独立列

    letters = list(OPTION_LABELS[:8])
    out = [list(r) for r in rows[:header_idx]]              # 标题/空行原样保留
    out.append(list(header[:combo]) + [f"选项{x}" for x in letters] + list(header[combo + 1:]))
    for row in rows[header_idx + 1:]:
        cell = row[combo] if combo < len(row) else ""
        segs, _leftover = _split_options(normalize_text(cell))
        opts = dict(segs)
        out.append(list(row[:combo]) + [opts.get(x, "") for x in letters] + list(row[combo + 1:]))
    return out


def _best_of_tables(tables: Sequence[list[list[str]]]) -> tuple[list[Question], list[BankIssue], list[str], dict]:
    """多张 Word 表格时，取能解析出最多题目的那一个。"""
    best: tuple[list[Question], list[BankIssue], list[str], dict] = ([], [], [], {})
    for rows in tables:
        for candidate in (rows, _expand_combined_options(rows)):
            try:
                qs, issues, header, cmap = rows_to_questions(candidate)
            except Exception:
                continue
            if len(qs) > len(best[0]):
                best = (qs, issues, header, cmap)
    return best


def load_bank(path: str | Path) -> BankLoadResult:
    """从文件加载题库。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"题库文件不存在：{p}")
    suffix = p.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"暂不支持的题库格式：{suffix}（支持 {'、'.join(SUPPORTED_SUFFIXES)}）")

    sheet = ""
    questions: list[Question] = []
    issues: list[BankIssue] = []
    header: list[str] = []
    cmap: dict = {}
    extra_warnings: list[str] = []

    if suffix in (".xlsx", ".xlsm"):
        sheet, rows = _read_xlsx(p)
        questions, issues, header, cmap = rows_to_questions(rows)
    elif suffix == ".json":
        rows = _read_json(p)
        questions, issues, header, cmap = rows_to_questions(rows)
    elif suffix in TEXT_SUFFIXES:
        rows = _read_delimited(p)
        questions, issues, header, cmap = rows_to_questions(rows)
    elif suffix in WORD_SUFFIXES:
        tables, lines = _read_docx(p)
        sheet = "段落文本" if lines else ""
        # 段落型与表格型都试一遍，取题目更多的那个
        q_text, i_text, meta_text = lines_to_questions(lines)
        q_tab, i_tab, h_tab, c_tab = _best_of_tables(tables)
        if len(q_tab) > len(q_text):
            questions, issues, header, cmap = q_tab, i_tab, h_tab, c_tab
            sheet = "表格"
        else:
            questions, issues = q_text, i_text
            extra_warnings = meta_text.get("warnings", [])
        if not questions:
            raise ValueError(
                "未能从 Word 文档中识别出题目。请确认文档包含“题型/题干/选项/答案”内容；"
                "若题目是图片，需要先转成文字。")
    elif suffix in PDF_SUFFIXES:
        lines = _read_pdf(p)
        sheet = "PDF 文本"
        q_text, i_text, meta_text = lines_to_questions(lines)
        extra_warnings = meta_text.get("warnings", [])
        if not q_text:                                   # 表格化兜底
            q_tab, i_tab, h_tab, c_tab = rows_to_questions(_pdf_lines_to_rows(lines)), None, None, None
            questions, issues = q_tab, i_tab
            header, cmap, sheet = h_tab or [], c_tab or {}, "PDF 表格"
        else:
            questions, issues = q_text, i_text
        if not questions:
            raise ValueError(
                "未能从 PDF 中识别出题目：可能是扫描件（图片）或版式过于特殊。"
                "请改用文本版 PDF、Word 或 Excel 题库。")
    else:                                                # pragma: no cover - 前面已拦截
        raise ValueError(f"暂不支持的题库格式：{suffix}")

    result = BankLoadResult(questions=questions, issues=issues, source=str(p),
                            sheet=sheet, header=header, column_map=cmap)
    if extra_warnings:
        result.column_map = dict(cmap or {})
        result.column_map.setdefault("warnings", extra_warnings)
    return result


# ---------------------------------------------------------------- 统计/导出
def bank_stats(questions: Iterable[Question]) -> dict:
    """统计题库结构。"""
    qs = list(questions)
    counts = {QType.SINGLE: 0, QType.MULTIPLE: 0, QType.JUDGE: 0}
    fixed = 0
    for q in qs:
        counts[q.qtype] += 1
        if q.fixed_order:
            fixed += 1
    return {
        "total": len(qs),
        "single": counts[QType.SINGLE],
        "multiple": counts[QType.MULTIPLE],
        "judge": counts[QType.JUDGE],
        "fixed": fixed,
    }


def questions_to_rows(questions: Iterable[Question]) -> list[list[str]]:
    """把题目转换为标准表格行（含列头），用于导出回 xlsx。"""
    header = ["题型", "题目标题", "选项A", "选项B", "选项C", "选项D", "选项E", "选项F",
              "选项G", "选项H", "解析", "答案"]
    rows = [header]
    for q in questions:
        opts = list(q.options) + [""] * (8 - len(q.options))
        answer = q.answer_display + ("（定）" if q.fixed_order else "")
        rows.append([q.qtype.value, q.stem, *opts[:8], q.analysis, answer])
    return rows


def export_questions_to_xlsx(questions: Iterable[Question], path: str | Path) -> Path:
    """把解析后的题库导出为标准 xlsx（可用于规范化用户的题库）。"""
    from openpyxl import Workbook

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "题库"
    for row in questions_to_rows(questions):
        ws.append(row)
    widths = [10, 60, 18, 18, 18, 18, 18, 18, 18, 18, 40, 12]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    ws.freeze_panes = "A2"
    wb.save(out)
    return out


def write_template_xlsx(path: str | Path, *, samples: int = 6) -> Path:
    """写出带示例行的题库模板。"""
    qs = build_sample_questions()[:samples]
    return export_questions_to_xlsx(qs, path)


def build_sample_questions() -> list[Question]:
    """内置示例题库（同时用于自测与用户上手）。"""
    raw = [
        ("单选题", "未经论证压缩合同约定工期，属于哪类重大事故隐患？",
         ["安全管理", "质量管理", "环境保护", "消防管理"],
         "依据判定标准，属于安全管理类。", "A"),
        ("单选题", "起重机械的安全装置不全、失效，属于哪类隐患？",
         ["安全管理", "起重机械安装拆卸", "高处作业", "施工用电"],
         "属于起重机械安装拆卸类。", "B"),
        ("多选题", "以下哪些属于安全管理类重大事故隐患？",
         ["未经论证压缩合同约定工期", "发包给不具备安全生产条件的企业",
          "无资质承揽电力建设工程", "转包或违法分包主体工程"],
         "以上均属安全管理类。", "ABCD"),
        ("多选题", "构支架吊装时，当柱脚接近杯底时，应从柱四周向杯口放入（ ）个木楔，"
                   "同时收紧四周缆风绳，确认缆风绳全部固定并使立柱基本（ ）后，才能松大钩。",
         ["3～4", "4～5", "垂直", "平行"],
         "两空依次为 4～5 与垂直，答案顺序固定。", "BC（定）"),
        ("判断题", "未经论证压缩合同约定工期属于重大事故隐患。", [],
         "属于重大事故隐患。", "正确"),
        ("判断题", "可以在电缆沟内充装易燃易爆危险品。", [],
         "禁止在电缆沟内充装易燃易爆危险品。", "错误"),
    ]
    questions: list[Question] = []
    for i, (t, stem, opts, analysis, ans) in enumerate(raw, start=1):
        qtype = parse_qtype(t)
        letters, judge, fixed = parse_answer(qtype, ans, len(opts) or 1)
        questions.append(Question(qid=f"{qtype.key}-{i:04d}", qtype=qtype, stem=stem,
                                  options=list(opts), answer_letters=letters,
                                  judge_answer=judge, fixed_order=fixed,
                                  analysis=analysis, src_row=i + 1))
    return questions


def make_txt_sample() -> str:
    """示例 txt 题库内容（制表符分隔）。"""
    lines = ["\t".join(["题型", "题目标题", "选项A", "选项B", "选项C", "选项D", "解析", "答案"])]
    for q in build_sample_questions():
        opts = list(q.options) + ["", "", "", ""]
        lines.append("\t".join([q.qtype.value, q.stem, *opts[:4], q.analysis,
                                q.answer_display + ("（定）" if q.fixed_order else "")]))
    return "\n".join(lines) + "\n"
