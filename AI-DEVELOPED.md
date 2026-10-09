# AI 开发声明 · AI Development Declaration

> 本文件是本项目的正式声明，与 `README.md` 中的说明一致。

## 一句话声明

**本项目（源码、文档、测试与构建脚本）由 AI 编写与维护，人类提出需求并验收结果。**

## 声明详情

| 项 | 说明 |
|---|---|
| 开发方式 | **AI 自主开发（AI-generated / AI-maintained）** |
| 使用模型 | **DeepSeek**（DeepSeek Harness 环境，模型 `deepseek-v4-flash`） |
| 开发代理 | DeepSeek Harness 编码代理，具备读写文件、执行命令、运行测试与打包的能力 |
| 人类角色 | 提出产品需求、提供题库样例、确认方案取舍、验收运行结果 |
| 开发过程 | 需求澄清 → 需求规格 → 概要设计 → **先写测试再实现** → 全量回归 → PyInstaller 打包 → exe 端到端验证 → 缺陷回归修复 |
| 质量证据 | 见 `docs/` 下的测试报告（含逐条验收对照）与缺陷分析与修复报告 |

## 重要提示（请使用者知悉）

1. **代码由 AI 生成**：虽然项目遵循"先测试、后实现、可复现"的工程流程（本仓库自带测试套件与 CI），
   但仍建议使用者**自行审阅代码**后再用于重要场合；
2. **AI 可能产生错误**：如发现缺陷，欢迎提交 Issue；本仓库的缺陷修复记录也会如实公开；
3. **不提供任何担保**：软件按"现状"提供，使用风险由使用者自行承担（详见 `LICENSE`）；
4. **模型与工具链**：代码并非人工逐行编写，注释与文档同样由 AI 生成；
   人类维护者负责需求定义与最终验收。

## 如何验证

```bash
pip install -r requirements.txt -r requirements-dev.txt
python tools/make_samples.py          # 生成合成示例题库与测试夹具
python -m unittest discover -s tests  # 运行全部自动化测试
```

CI（`.github/workflows/build.yml`）会在每次推送时重复上述步骤并打包 Windows 单文件 exe。

---

_本声明随项目一起公开，用于明确 AI 在项目中的角色与责任边界。_
