# AI 开发入口

## 项目与事实来源

- 项目目标是 Laya API Key 管理与计费平台；当前仅实现模型 HTTP API 和 CLI。
- 已确认目标见 [平台需求](docs/20261002-Laya平台-需求.md)，不要把待实现功能当现状。
- 当前环境：Python 3.12.5、Laya 0.3.23、FastAPI 0.142.2、Uvicorn 0.54.0。
- 版本是 2026-10-02 的安装快照，非锁定版本；以实际依赖元数据复核。
- `api.py`：参数模型、HTTP 路由、模型生命周期、推理锁、错误映射。
- `customer_service_test.py`：客服分析、业务分流规则与 CLI；并非自动化测试。
- `run-api` / `run-laya`：启动脚本；`requirements-api.txt` 仅声明 API 依赖。

## 渐进加载

1. 先读本文件和 [规则索引](docs/AI_RULES.md)。
2. 按任务读取 [项目事实与审计](docs/PROJECT_KNOWLEDGE.md) 的相关章节及源代码。
3. 复杂变更读取 [Spec 指南](docs/SPEC_GUIDE.md) 和已确认需求。
4. 操作说明见 [README](README.md)，不要把聊天记录当作长期契约。

## 核心红线

- 不擅自修改 API 字段、状态码、模型类型和客服阈值。
- 不提交密钥、客户原文、缓存、虚拟环境或本机敏感配置。
- 不无需求引入依赖、数据库、服务、空壳分层或基础设施。
- 功能与修复必须同步对应验证；缺陷先复现并建立失败测试。
- 部署、架构、安全、性能和依赖变更先评估兼容与回滚。
- 单进程单模型和推理锁是当前约束，变更前评估 MPS 内存及并发。
- 不静默解决需求、规则、知识和代码冲突；报告位置、影响和方案。
- 不自动提交、不清理未确认可删除的文件；保留用户已有修改。
- 不创建、删除、移动或重命名 `docs/` 下的目录。

## 修改前后

- 修改前确认范围，读取相关源码和契约，检查版本控制及工作区状态。
- 简单任务最小修改；契约、依赖、架构等复杂任务先写 Spec。
- 修改后执行可用检查，更新相关文档，报告未验证项与风险。
- 当前没有测试套件、Lint、类型检查及构建配置，不得声称这些检查通过。

## 当前可执行命令

以下均在项目根目录执行：

```bash
uv pip check --python .venv/bin/python --cache-dir .uv-cache
zsh -n run-api run-laya
.venv/bin/python -c 'import ast,pathlib; [ast.parse(pathlib.Path(p).read_text()) for p in ("api.py","customer_service_test.py")]'
.venv/bin/python -c 'import api; print(api.app.openapi()["paths"].keys())'
zsh run-api
.venv/bin/python customer_service_test.py --json "请帮我退款"
curl http://127.0.0.1:8000/health
```

启动和推理不是纯静态检查，按任务需要执行，避免重复启动占用端口。
提交前执行 `git diff --check` 与 `git diff --cached --check`，并审查暂存文件。
只有用户明确要求时创建 Commit。
