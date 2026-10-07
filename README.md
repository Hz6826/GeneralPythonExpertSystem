# 通用专家系统 · GeneralPythonExpertSystem

一个用 Python + Flask 写的**通用前向推理专家系统**。核心只有三样东西 ——
**事实（Fact）**、**规则（Rule）**、**工作记忆（Working Memory）**；
配一个零依赖的网页控制台，可以单步 / 连续推理、逐条查看规则的 IF → THEN、载入不同领域的知识库。

后端不依赖任何推理框架，前端不依赖任何前端框架。

- 语言 / 运行时：Python ≥ 3.14
- 直接依赖：仅 Flask + Werkzeug（见 [pyproject.toml](pyproject.toml)）
- 前端：原生 HTML + CSS + JavaScript
- 许可证：[MIT](LICENSE)
