# AI 开发入口

## 项目与事实来源

- 项目目标是 Laya API Key 管理与计费平台；已实现模型 HTTP API、CLI、邮箱密码登录、
  API Key 生命周期与 Bearer 推理鉴权、调用记录、Decimal 计费、统计查询和四个页面。
- 已确认目标见 [平台需求](docs/20261002-Laya平台-需求.md)，不要把待实现功能当现状。
- 当前环境：Python 3.12.5、Laya 0.3.23、FastAPI 0.142.2、Uvicorn 0.54.0、
  MySQL 9.6.0、Node 22.22.3。
- 版本是 2026-10-02 的安装快照，非锁定版本；以实际依赖元数据复核。
- `backend/app/`：后端。`main.py` 组装与 lifespan，`api/v1/` 路由，`schemas/` 契约，
  `services/` 账号/客服规则/模型运行时，`core/` 配置与哈希，`db/` 连接与建表。
- `backend/migrations/`：可审查 DDL 与回滚，是表结构唯一来源。
- `frontend/`：Tailwind 页面，`npm run build` 产出 `dist/`，未构建时 `/login` 返回 500。
- `customer_service_test.py`：客服分析 CLI 入口，业务规则已迁到
  `backend/app/services/customer_service.py`；并非自动化测试。
- `run-api` / `run-laya`：启动脚本，`run-api` 以 `PYTHONPATH=backend` 启动 `app.main:app`；
  `requirements-api.txt` 声明 API、鉴权与数据库驱动依赖。
- `backend/app/manage.py`：显式迁移、首个管理员与recover-calls CLI；恢复默认只读，--apply仅恢复可信成功回执的单调用，不接受密码命令行参数，不自动提升已有普通用户权限。
- `Dockerfile` / `compose.yaml`：仅 external 模式的容器部署，默认宿主 loopback、独立 MySQL；私有配置用 `.env.deploy`，不可覆盖本机 `.env`。
- `.env`：本机 MySQL 凭据，已被 Git 忽略；未配置数据库凭据时启动失败，容器由环境变量提供。

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
- 请求限流默认关闭，同用户全部Key/推理入口共享固定分钟RPM和在途名额，仍只支持单worker；不是Token硬配额。
- 成功回执不含正文；恢复补账沿原价格且幂等。无回执/未知/矛盾不能推算收费；可选Idempotency-Key仅存摘要，同用户共享，重复409，不回放回复、不自动过期删除。
- 不静默解决需求、规则、知识和代码冲突；报告位置、影响和方案。
- 不自动提交、不清理未确认可删除的文件；保留用户已有修改。
- 不创建、删除、移动或重命名 `docs/` 下的目录。

## 修改前后

- 修改前确认范围，读取相关源码和契约，检查版本控制及工作区状态。
- 简单任务最小修改；契约、依赖、架构等复杂任务先写 Spec。
- 修改后执行可用检查，更新相关文档，报告未验证项与风险。
- 当前有 `backend/tests` unittest 回归和前端构建；未配置 Lint 与类型检查，不得声称这些检查通过。

## 当前可执行命令

以下均在项目根目录执行：

```bash
uv pip check --python .venv/bin/python --cache-dir .uv-cache
zsh -n run-api run-laya
PYTHONPATH=backend .venv/bin/python -c 'import ast,pathlib; [ast.parse(pathlib.Path(p).read_text()) for p in ["customer_service_test.py", *sorted(pathlib.Path("backend").rglob("*.py"))]]'
PYTHONPATH=backend .venv/bin/python -c 'import app.main as m; print(sorted(m.app.openapi()["paths"].keys()))'
cd frontend && npm run build && cd ..
zsh run-api
.venv/bin/python customer_service_test.py --json "请帮我退款"
curl http://127.0.0.1:8000/health
```

启动需要本机 MySQL 运行且根目录存在 `.env`（见 README 前置条件）。
启动和推理不是纯静态检查，按任务需要执行，避免重复启动占用端口；
端口被占用时可用 `zsh run-api --port 8010`，不要终止非本次会话启动的进程。
提交前执行 `git diff --check` 与 `git diff --cached --check`，并审查暂存文件。
只有用户明确要求时创建 Commit。
