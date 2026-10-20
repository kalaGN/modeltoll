# AI 开发入口

## 项目与事实来源

- 项目目标是 Laya API Key 管理与计费平台；已实现模型 HTTP API、CLI、邮箱密码登录、
  API Key 生命周期与 Bearer 推理鉴权、调用记录、Decimal 计费、统计查询和独立前端。
- 已确认目标见 [平台需求](docs/20261002-Laya平台-需求.md)，不要把待实现功能当现状。
- 当前环境：Python 3.12.5、Laya 0.3.23、FastAPI 0.142.2、Uvicorn 0.54.0、
  MySQL 9.6.0、Node 22.22.3。
- 版本是 2026-10-02 的安装快照，非锁定版本；以实际依赖元数据复核。
- `backend/app/`：后端。`main.py` 组装与 lifespan，`api/v1/` 路由，`schemas/` 契约，
  `services/{access,inference,metering,platform}/` 按业务域组织服务，`core/` 配置/哈希/纯校验/UTC 格式化，
  `models/` 每表一个 SQLAlchemy 映射，`repositories/` 按操作域查询/写入/锁与结果投影，
  `db/engine.py` 惰性 Engine、`db/session.py` 短 Session/事务，`db/migrations.py` 执行既有 SQL。
  Service 决定事务边界，不直接执行 SQL 或 ORM 查询；Repository 不自行提交或建立连接。
  `db/connection.py` 原生连接仅供迁移执行器使用，不供业务调用。
- `api/inference_support.py` 共享推理 HTTP 协调；路由不得互相导入内部函数。
  `schemas/` 不依赖 services/db；`integrations/openai_client.py` 负责上游协议与传输，
  不依赖服务或数据库。`services/platform/branding.py` 管理品牌，`services/platform/admin_overview.py` 管理平台聚合。
- `backend/migrations/`：可审查 DDL 与回滚，是表结构唯一来源。
- `frontend/`：Vue 3 + TypeScript + Vue Router + Vite + Tailwind 独立 SPA。
  唯一 HTML 入口 frontend/index.html，页面在 src/pages/{auth,console,admin}/*.vue；
  layouts/components/composables/api/styles 分别负责布局、复用组件、组合逻辑、接口和样式。
  2026-10-20 用户确认 Vue 重做，替代旧 pages/templetes 与原生页面入口规则，不保留双入口。
  npm run build 先 vue-tsc 类型检查再输出 dist/index.html + assets/哈希资源；禁止修改 dist。
  dev 固定 5173 loopback + strictPort，同源代理到 8000；生产独立 Nginx，不回退 API 错误到 HTML。
  导航/角色守卫归 router，实际数据权限仍由 API 验证；Cookie/CSRF 与完整 Key 安全边界不变。
  Node 要求见 frontend/package.json engines，测试依赖最低 22.22.2 / 24.15。
- `backend/tests/{unit,contract,integration,e2e}`：分类回归，`support/` 存共享合成辅助代码；
  默认 unittest 入口仍可发现全部用例，真实 MySQL/容器测试需显式 opt-in。
- `.python-version` 固定开发解释器系列 3.12；`pyproject.toml` 仅配置 uv pip 默认虚拟环境，
  不是打包或依赖锁文件。依赖唯一来源仍为 `requirements-api.txt`，不改用 `uv sync`。
- `customer_service_test.py`：客服分析 CLI 入口，业务规则已迁到
  `backend/app/services/inference/customer_service.py`；并非自动化测试。
- `run-api` / `run-laya`：启动脚本，`run-api` 以 `PYTHONPATH=backend` 启动 `app.main:app`；
  `requirements-api.txt` 声明 API、鉴权与数据库驱动依赖。
- `backend/app/manage.py`：显式迁移、首个管理员与recover-calls CLI；恢复默认只读，--apply仅恢复可信成功回执的单调用，不接受密码命令行参数，不自动提升已有普通用户权限。
- `Dockerfile` 只构建 Python API；`frontend/Dockerfile` 构建 Nginx 前端。
  `compose.yaml` 仅 external 模式，frontend 对宿主 loopback 发布 APP_PORT，app/db 不发布端口。
  FORWARDED_ALLOW_IPS=* 仅用于此受控内部代理网络，不用于直接对外暴露的 API。
  私有配置用 `.env.deploy`，不可覆盖本机 `.env`，不删除既有 MySQL 卷。
- `.env`：本机 MySQL 凭据，已被 Git 忽略；未配置数据库凭据时启动失败，容器由环境变量提供。

## 渐进加载

1. 先读本文件和 [规则索引](docs/AI_RULES.md)。
2. 按任务读取 [项目事实与审计](docs/PROJECT_KNOWLEDGE.md) 的相关章节及源代码。
3. 复杂变更读取 [Spec 指南](docs/SPEC_GUIDE.md) 和已确认需求。
4. 操作说明见 [README](README.md)，不要把聊天记录当作长期契约。

## 核心红线

- 不擅自修改 API 字段、状态码、模型类型和客服阈值。
- ORM 不自动建表或修改表；DDL 唯一来源仍是 migrations。Session 按操作/线程独立，
  不跨密码哈希、模型锁等待、推理或上游 HTTP 持有事务，不向 API 返回 ORM 实体。
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
- 当前有 backend/tests unittest、前端 vue-tsc/Vitest/Node 测试与构建；后端无类型检查、全项目无 Lint，不得冒称通过。

## 当前可执行命令

以下均在项目根目录执行：

```bash
uv pip check --python .venv/bin/python --cache-dir .uv-cache
zsh -n run-api run-laya
PYTHONPATH=backend .venv/bin/python -c 'import ast,pathlib; [ast.parse(pathlib.Path(p).read_text()) for p in ["customer_service_test.py", *sorted(pathlib.Path("backend").rglob("*.py"))]]'
PYTHONPATH=backend .venv/bin/python -c 'import app.main as m; print(sorted(m.app.openapi()["paths"].keys()))'
cd frontend && npm run build && cd ..
npm --prefix frontend run dev
npm --prefix frontend run typecheck
npm --prefix frontend test
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests
zsh run-api
.venv/bin/python customer_service_test.py --json "请帮我退款"
curl http://127.0.0.1:8000/health
```

启动需要本机 MySQL 运行且根目录存在 `.env`（见 README 前置条件）。
启动和推理不是纯静态检查，按任务需要执行，避免重复启动占用端口；
端口被占用时可用 `zsh run-api --port 8010`，不要终止非本次会话启动的进程。
提交前执行 `git diff --check` 与 `git diff --cached --check`，并审查暂存文件。
只有用户明确要求时创建 Commit。

前端 dev 使用 Vite HMR；`npm --prefix frontend run watch` 只监视生产构建。
dev 和 run-api 是独立长驻进程，分别在两个终端运行；本机页面入口是 5173，不是 8000/login。
代理集成检查用 `npm --prefix frontend run test:server`（随机本机端口）；可选已有 Nginx 验证用
`npm --prefix frontend run test:nginx`。两者均只操作合成环境，不启动 Docker 或访问真实账号。
前端契约测试先构建再执行。浏览器隔离回归与现有 Playwright 运行库的使用见
[Vue 重做任务](docs/20261020-Vue前端重做-任务.md)，不读取真实账号或调用管理写接口。
