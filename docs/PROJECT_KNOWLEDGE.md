# 项目事实、知识索引与现状审计

核查日期：2026-10-02（同日登录与平台实施后更新）。源码及运行环境为主要依据；
版本与文件状态会变化，使用前复核。
本文件集中记录知识，归档在 `docs/`，不散落重复文档。

项目目标已扩展为 [Laya API Key 管理与计费平台](20261002-Laya平台-需求.md)。
邮箱密码登录与注册、API Key 生命周期、Bearer 推理鉴权、调用记录、Decimal 计费、
统计查询与四个页面均已实施并本机验证，见
[任务记录](20261002-Laya平台-任务.md)；失败与超时调用的计费规则、统计时区与
边界仍待产品确认。
下文描述当前代码，不将需求目标冒充已具备的功能。

## 知识索引

| 章节 | 内容 | 何时读取 |
| --- | --- | --- |
| 项目盘点 | 技术栈、入口、目录、基础设施 | 入门与环境排查 |
| 架构与生命周期 | 真实依赖链、并发、配置 | 模型、API 与性能修改 |
| 当前契约 | 请求、响应、限制和错误 | 调用与兼容性修改 |
| 审计 | 缺失机制、证据、风险和建议 | 排期、安全与部署评估 |

知识只记录源码支持的事实；不确定标“待确认”。新增章节更新索引。
强制约束归 [AI_RULES.md](AI_RULES.md)，单次变更归 Spec，操作方法归 README。

## 项目盘点

- 形态：本机 HTTP 服务（后端 + 同源页面）+ CLI。后端在 `backend/app`，
  入口 `app.main:app`；前端在 `frontend/`，Tailwind 构建到 `frontend/dist`。
- `backend/app/main.py` 是 ASGI 入口与组装点；`backend/app/api/v1/` 放路由；
  `backend/app/services/` 放账号、Key 生命周期与鉴权、价格与记账、调用协调、
  统计查询、客服规则与模型运行时；`backend/app/schemas/` 放请求与查询契约。
- 前端页面在 `frontend/src/`（`login.html`、`api-keys.html`、`usage.html`、
  `billing.html` 共用 `app.js`），`npm run build` 产出 `frontend/dist/`，
  由后端以 `/assets` 同源提供；页面路由 `/login`、`/keys`、`/usage`、`/billing`
  未构建时返回 500 提示。
- `run-api` 是 zsh/Uvicorn 启动器（注入 `PYTHONPATH=backend`），`run-laya` 是 Laya
  命令行启动器，`customer_service_test.py` 是客服 CLI 入口。
- 当前 Python 3.12.5、Laya 0.3.23、FastAPI 0.142.2、Uvicorn 0.54.0、Pydantic 2.13.5、
  Torch 2.14.1、Transformers 5.18.0、HTTPX 0.28.1、PyMySQL 1.2.3、
  cryptography 50.0.2、argon2-cffi 25.1.0；Node 22.22.3、Tailwind 4.3.3。
  来源：`.venv/bin/python` 与 `importlib.metadata.version`，不是依赖锁。
- 包管理：Python 侧 `requirements-api.txt` 声明 API、鉴权与数据库驱动，是范围约束
  而非版本锁定，无 Python 锁文件；前端 `frontend/package.json` 有 `package-lock.json`。
- 已安装包一致性可用 `uv pip check --python .venv/bin/python --cache-dir .uv-cache`。
- 数据库：本机 MySQL 9.6.0，库 `laya_platform`，专用账号 `laya_app@127.0.0.1`，
  表 `users`、`user_sessions`、`login_throttle`、`api_keys`、`pricing_rules`、
  `api_calls`、`usage_charges`，DDL 与回滚在 `backend/migrations/`（0001/0002/0003）。
  `pricing_rules` 有 `v1` 种子规则（¥1 / 1,000,000 输入 Token，CNY，
  计费策略 `succeeded_only_v1`），历史调用固定其 `pricing_rule_id`。
  未见缓存服务、MQ、搜索、对象存储或迁移框架。凭据在根目录 `.env`（已忽略）。
- 文件持久化另有 `.hf-cache` 模型缓存；`.venv`、`.uv-cache`、`.idea`、`__pycache__`、
  `torchinductor_wangfei`、`node_modules`、`frontend/dist` 为本机目录，不擅自删除。
- 未见 Docker、Kubernetes、反向代理、进程管理配置或 CI；运行方式是终端进程。
- Git 于 2026-10-02 初始化；`.gitignore` 排除虚拟环境、模型/工具缓存、IDE、字节码、
  日志、本机密钥、`node_modules/` 与 `frontend/dist/`。团队分支策略待确认。
- 没有自动化测试文件/配置；客服文件名含 test 但运行的是 CLI 推理。
- 未安装 pytest、ruff、mypy、build，也没有 formatter、Lint、覆盖率配置。

## 架构与生命周期

登录链路：浏览器 → `/login`（`frontend/dist/login.html` + CSRF Cookie）→
`POST /v1/auth/*` → Pydantic 校验 → CSRF 依赖 → `services/accounts` → MySQL 短事务。

Key 与统计链路：`/keys`、`/usage`、`/billing` 页面要求登录会话（未登录 302 到
`/login`）→ `/v1/api-keys*` 走会话 + CSRF → `services/api_keys`；
`/v1/usage/*`、`/v1/billing/*` 走 `dependencies.require_user` → `services/statistics`，
所有 SQL 都带 `c.user_id = %s` 范围，明细用 `(started_at, id)` keyset 游标分页。

推理链路：HTTP → `Authorization: Bearer` → `api_keys.authenticate`（SHA-256 查库，
撤销/无效 401、停用账号 403）→ Pydantic 校验 → `inference.begin` 插入 `accepted`
调用行并固定价格规则 → `model_runtime.inference_lock`（拿到锁后 `still_valid` 重检）
→ `mark_running` → 客服 `analyse_with_usage` 或 `Router.predict` → Laya multilingual
→ 终态、用量与费用在同一短事务写入（`succeeded`/`failed`/`interrupted`）→
JSON 响应 + `X-Request-Id`。事务不跨推理持有。

lifespan 顺序是先 `db/models.init_db()` 执行迁移 SQL，再创建 `Router(max_loaded=1)`
并加载 multilingual，保存到 `app.state`；任一失败都阻止应用启动。同步路由由框架在
线程池中执行，推理锁把两类预测串行化。当前 lifespan 退出没有显式模型清理逻辑。
`services/model_runtime.py` 持有推理锁与模型构建，`main.py` 注入运行时，
底层模块不反向 import app。

数据库连接按操作获取并立即释放（`db/session.py` 的 `cursor()` 自动提交、
`transaction()` 短事务）；口令 Argon2 验证在写事务之外完成，避免长时间持有事务。
没有跨请求共享的可变 Session/事务对象。

`run-api` 设置 `HF_HOME` 为项目缓存、`HF_HUB_OFFLINE=1`、`PYTHONPATH=backend`、
默认 `LAYA_DEVICE=mps`，绑定 `127.0.0.1:8000`，单 worker；尾部可追加 Uvicorn 参数。
`core/config.py` 只接受 mps/cpu。客服 CLI 通过 `sys.path` 引入 backend 后复用同一服务，
自身不强制离线。`laya` 命令行启动器同样不强制离线。
无外部业务写操作；直接非离线启动可能由 Laya 检查/下载 HF 模型。

## 当前契约

| 方法与路径 | 请求 | 成功响应 |
| --- | --- | --- |
| GET `/health` | 无业务参数 | status、model、device |
| POST `/v1/customer-service/analyze` | `Authorization: Bearer <Key>`；message：1–8000 字符，禁止纯空白 | 客服分析对象 + `X-Request-Id` |
| POST `/v1/predict` | `Authorization: Bearer <Key>`；state、questions、可选 lang（默认 zh） | 原生 Laya answers、usage、routing 等 + `X-Request-Id` |
| POST `/v1/auth/register` | email、password（8–128） | 201 与 `{code,user}` |
| POST `/v1/auth/login` | 同上 | `{code,user}` 并下发 `laya_session` Cookie |
| GET `/v1/auth/me` | 会话 Cookie | `{code,user}` |
| POST `/v1/auth/logout` | 会话 Cookie | `{code:"ok"}` 并清除 Cookie |
| GET `/v1/auth/csrf` | 无 | `{code,csrf_token}` 并下发 `laya_csrf` Cookie |
| POST `/v1/api-keys` | 会话 + CSRF | 201 与 `{code,api_key,secret,call_example}`，`secret` 仅此一次 |
| GET `/v1/api-keys` | 会话 | `{code,items,summary{total,active,revoked}}`，`items[].display` 脱敏 |
| POST `/v1/api-keys/{id}/revoke` | 会话 + CSRF，body `{confirm:true}` | `{code,api_key}`；他人或不存在同为 404 |
| GET `/v1/usage/summary` | 会话 + `from`/`to`/`api_key_id`/`endpoint` | `range`、`totals`、按 UTC 日的 `series` |
| GET `/v1/usage/calls` | 同上 + `limit`/`cursor` | `items[]`（含 `request_id`、状态、Token、耗时）、`next_cursor`、`has_more` |
| GET `/v1/billing/summary` | 同 usage/summary | 追加 `price`（当前价格规则）与费用 `totals` |
| GET `/v1/billing/charges` | 同上 | 逐条费用（计费 Token、单价、金额、价格版本） |

管理接口的五个写操作（register/login/logout、创建与撤销 Key）要求 `X-CSRF-Token`
与 `laya_csrf` Cookie 一致，缺失或不一致返回 403 `csrf_failed`。鉴权失败统一为平铺
`{"code","message"}`：401 `invalid_credentials`（错误密码与不存在邮箱同体同码）、
401 `unauthenticated`、401 `invalid_api_key`（缺失/格式错/无效/已撤销同体同码）、
403 `account_disabled`、404 `api_key_not_found`（他人与不存在同为 404）、
409 `email_already_registered`、429 `account_locked`、400 `invalid_range`。
422 仍是 FastAPI `detail` 列表结构。
`laya_session` 为 HttpOnly、SameSite=Lax、`Max-Age=604800`、`secure=False`
（仅 loopback，对外暴露前必须改 True）。限速按 邮箱+来源IP 计数：
15 分钟内 5 次失败锁定 15 分钟。计数由单条 `INSERT ... ON DUPLICATE KEY UPDATE` 完成
读改写（并发不丢计数），`locked_until` 的赋值必须排在 `failed_count` 之前，
否则 MySQL 从左到右求值会按自增后的新值判阈值、提前一次就锁定。
`/login` 与 `/register` 返回同一页面（`?mode=register` 或路径决定表单文案）。
`/` 按会话跳转：已登录 → `/keys`，未登录 → `/login`（原 `/me` 页面路由已删除，
当前账号只由 `GET /v1/auth/me` 提供）。受保护页面响应带 `Cache-Control: no-store`，
`/assets` 带 `no-cache`，避免浏览器缓存导致会话校验被跳过。
统计缺省窗口上界取服务端当前时刻（含亚秒精度），因此刚提交的调用立刻可见。

请求使用 JSON；推理接口只接受 Bearer Key，登录会话不能代替。统计接口支持
`from`/`to`（UTC，`to` 为开区间；只给日期按整日；带 `Z` 或 `+08:00` 偏移的入参先换算到
UTC 再去掉 tzinfo，与库内 naive UTC 列同基准）、`api_key_id`、`endpoint` 过滤，
`limit` 默认 20、上限 100，`cursor` 为 base64url 的 `(started_at, id)` keyset 游标；
缺省时间窗口为最近 30 天（采用值，待产品确认）。`/usage` 与 `/billing` 页面把
`from`/`to`/`api_key_id`/`limit` 暴露为日期区间、密钥下拉与 20/50/100 每页条数，
筛选后分页游标重置；页面时间一律按 UTC 渲染并标注 UTC。
客服响应字段：message、category、category_name、category_probability、recommended_action、
priority、needs_human、signals、model。分类有 refund、technical_help、billing_question、
information、cancellation、other（来自 Laya triage 预设及脚本映射）。
响应体保持不变；服务层另有 `analyse_with_usage` 返回原生 `usage`，只用于内部记账，
不加入对外响应（设计 §14）。

客服需要人工的任一条件：紧急概率 ≥0.5、不满评分 ≥2、流失概率 ≥0.5，
或分类为 refund/cancellation。高优先级：紧急 ≥0.5、不满 ≥2.5 或流失 ≥0.75；
其余不满 ≥1.5 或流失 ≥0.5 为中，否则低。证据：`analyse`。
这些是脚本规则，未见独立业务政策文档；不能仅凭测试通过确认业务合理性。

结构化接口固定 multilingual；state 可为字符串、对象或列表，JSON 序列化后最多
16000 字符。questions 1–20 项；instructions 1–2000 字符且非纯空白；
choice/score 的 criteria 2–20 项，每项非空且 ≤1000 字符。
noul 可省略 criteria；有对象时只允许 true/false 键。lang 2–20 字符，无语言白名单。
Pydantic 模型未设置 extra=forbid：未知字段默认忽略，不声称会拒绝额外字段。

成功 200；参数验证 422（FastAPI detail 列表），原生预测捕获 ValueError/TypeError
也返回 422（detail 字符串）；推理异常 500（通用中文 detail），日志保留 traceback。
Key 鉴权失败 401/403 在进入推理锁之前返回，不加载模型。模型未返回 `input_tokens` 时
先落 `failed` / `error_code=usage_unavailable` / `billing_status=pending`，对外同为
500 `usage_unavailable`（2026-10-03 用户列为缺陷后由 200 改来，属状态码变更，不入账）。
终态记账写入失败时返回
500 `billing_unavailable`，不对外宣称成功。422 的校验失败发生在请求解析阶段，
不产生调用记录。管理接口有平铺业务码，推理接口仍无统一响应外壳；错误结构并非
完全统一。
`/docs`、`/redoc` 和 `/openapi.json` 为 FastAPI 当前默认文档路由。
无版本废弃策略；当前路径只使用 /v1，不推断已有多版本治理。

## 现状审计

P1 表示涉及未来对外暴露、资源耗尽或明显验证缺口；P2 为维护/复现性问题。
这是建议优先级，不是已确认的生产事故。

| 优先级 | 证据与问题 | 影响 | 建议（本次不实施） |
| --- | --- | --- | --- |
| ~~P1~~ 已收敛 | 两个推理接口原先无鉴权（需求 R04） | 2026-10-02 接入 Bearer API Key 校验，缺失/无效/已撤销 401、停用账号 403，且在加载模型前返回 | Cookie `secure=False` 仍只适用于 loopback；Key 级速率限制待安全 Spec |
| P1 | 失败与超时调用的计费策略未经产品确认，当前采用 `succeeded_only_v1`；拿不到用量时置 `pending` | 账务口径可能与最终政策不一致，`pending` 行需要补偿处理 | 产品确认后新增策略版本与补偿流程，改动必须带对账验证 |
| P1 | `accepted`/`running` 遗留行只作为可恢复记录，没有启动时收敛流程 | 进程被强杀后统计会长期显示“进行中” | 设计超时扫描把遗留行置为 `interrupted`，保持不计费 |
| P1 | inference_lock 无排队截止/请求级推理超时 | 并发请求占线程排队，超时客户端不代表推理取消 | 明确队列上限、超时和取消策略并验证 |
| P1 | 仅字段字符校验，无请求体总字节/深度边界 | 超大或深嵌套 JSON 在校验前消耗资源 | 评估服务/代理身体积限制及边界样本 |
| P1 | 没有自动化测试，登录与推理均靠本机端到端命令验证 | 契约、阈值、限速和错误分支易回归 | 后续变更同步 Unit/契约/集成测试 |
| ~~P1~~ 已收敛 | 本机三张表曾由原型 DDL 先建，迁移用 `IF NOT EXISTS` 不补差异 | 2026-10-02 已用两条新增型 `ALTER TABLE` 补上 `chk_users_status` 与 `idx_throttle_locked`，未清空数据 | 新环境仍直接执行 `0001_auth.sql`；结构差异用 `init_db()` 与 `information_schema` 复核 |
| P2 | requirements-api.txt 非完整依赖，未锁版本 | 新环境不能仅靠此文件完整复现模型服务 | 明确完整依赖与锁定策略后再修改配置 |
| P2 | 已初始化 Git 并添加忽略规则；缓存和 IDE 目录仍在根目录 | 手工强制添加仍可能误跟踪本机文件 | 每次提交前审查暂存清单，避免 git add -f |
| P2 | 调用已有 `X-Request-Id` 与库内记录，日志仍无统一脱敏策略 | 故障可关联到调用行，但日志字段与隐私边界未定义 | 设计结构化诊断和脱敏规则，不记客户原文 |
| P2 | 统计页面趋势按 UTC 日分桶，与账务明细同窗口但展示口径为采用值 | 跨时区使用时趋势与账单日界可能不一致 | 确认统计时区与日界后固定口径并补测试 |
| P2 | health 仅报告启动后状态；无模型功能探测 | 200 不证明后续推理始终可用 | 区分存活、就绪与功能探针并评估开销 |
| P2 | 无吞吐、P95/P99、内存或失败率报告 | 无法给出生产容量或可靠性承诺 | 待建立可复现冷/热启动及并发基线 |
| P2 | 概率及规则阈值有代码，无业务验收集 | 单条分类成功不证明普遍中文客服准确性 | 用合成/授权脱敏样本建立验收集 |
| P2 | lifespan 无显式退出动作，无部署配置 | 重启、排空、失败恢复要求未确定 | 确认运行环境与优雅退出验收 |
| P2 | run-laya/CLI 未强制离线，API 启动器强制离线 | 不同入口网络/缓存行为有差异 | 文档保持区分；如需统一先确定需求 |

未发现默认脚手架业务代码；不因 FastAPI 存在就假设有 CORS 或权限。
49 个已安装包兼容性通过，不等于不存在未使用依赖；仅凭包列表无法确认可删对象。
README 的本机 URL 是服务运行时地址，不是外网失效链接。
SQL 全部是 `backend/migrations/` 内的固定 DDL 与参数化语句，无字符串拼接；
未见上传、模板或自定义反序列化路径。

## 验证记录与待确认

- 2026-10-02：uv pip check 检查 43 包，安装包互相兼容。
- zsh -n 检查两启动器通过；导入 api 并生成 OpenAPI 3.1.0，三个路径存在。
- unittest discover 找到 0 个测试（退出非成功），不能记为全量测试通过。
- 初次审计时 git status/log 因非 Git 仓库失败；后续按用户要求初始化，
  提交前执行 Git diff 格式检查与暂存清单审查。
- 未配置 Lint、类型检查；不新增依赖来伪装完成这些检查。
- 2026-10-02 登录实施后：uv pip check 49 包兼容；`zsh -n` 两启动器通过；
  `PYTHONPATH=backend` 下 21 个 Python 文件 AST 解析通过，OpenAPI 生成 8 个路径；
  `frontend` Tailwind 构建产出 `dist/app.css`（18.5 KB）与 `dist/login.html`。
- 同日端到端实测（服务跑在 8010，8000 被更早启动的旧 `api:app` 进程占用且未改动）：
  注册 201、登录 200 下发 HttpOnly Cookie、重复注册 409、错误密码与不存在邮箱
  同为 401 且响应体一致、5 次失败后 429、登出后 `/v1/auth/me` 401、缺 CSRF 403、
  密码过短 422；`/v1/predict` 与 `/v1/customer-service/analyze` 仍 200 且阈值语义不变。
- 库内取证：`password_hash` 为 `$argon2id$v=19$m=65536,t=3,p=4$` 开头、长度 97，
  明文密码匹配 0 行；`token_hash` 为 64 位十六进制；`expires_at` 为创建时间 + 7 天。
- 页面仅经 DOM 结构与计算样式取证（渐变背景、`#2563eb` 按钮、12px 圆角生效）；
  内置浏览器无可见视口，未完成像素级视觉比对，指针点击不可用。
- 同日 DDL 收敛：两条新增型 `ALTER TABLE` 补齐 `chk_users_status` 与 `idx_throttle_locked`，
  `information_schema` 复核约束与索引齐全、`users` 5 行数据未丢；`status='banned'` 被
  `3819` 拒绝证明 CHECK 生效；随后 8010 再次注册 201、登录 200、`/me` 200、登出 200、
  登出后 `/me` 401。
- 2026-10-02 平台实施后（服务跑在 8020，8000/8010 上更早启动的进程未改动）：
  `uv pip check` 49 包兼容；`zsh -n` 两启动器通过；29 个 Python 文件 AST 解析通过；
  `node --check frontend/src/app.js` 与 `npm run build` 通过（`dist/` 含 4 个页面、
  `app.css` 23.8 KB、`app.js` 19.0 KB）；OpenAPI 14 个路径。
  `customer_service_test.py --json "请帮我退款"` 输出 `refund` / 概率 1.0 / 需人工，
  CLI 行为未变。
- Key 与鉴权实测：创建返回 51 字符 `laya_sk_` 密钥一次，列表显示 `laya_sk_xosi****jntY`
  脱敏；无 Key、错误 scheme、伪造 Key、已撤销 Key 调用同为 401 且不进推理；
  撤销后 `still_valid` 为假；撤销他人与不存在 ID 同为 404。
- 真实模型端到端：`/v1/predict` 与 `/v1/customer-service/analyze` 带 Bearer 均 200，
  响应含原生 `usage`，响应头 `X-Request-Id` 与 `api_calls.id`、统计明细 `request_id`
  一致；单账号 28 次调用中 25 次成功，计费 6,374 Token → ¥0.006374，与
  `1 Token = 1e-6 元` 逐条对账相符；`/v1/usage/summary` 与 `/v1/billing/charges`
  汇总一致（`charged_amount_yuan` 相同）。
- 生命周期取证（直接驱动 `services/inference`）：`failed(model_error,500)` →
  `not_billable`/`policy_succeeded_only`；`interrupted(client_disconnected,499)` →
  `not_billable`/原因记录；`failed(usage_unavailable,500)` → `billing_status=pending`；
  三者均无 `usage_charges` 行，`UNIQUE(call_id)` 未触发重复扣费。
- 页面取证：浏览器登录后 `/keys` 创建密钥（弹窗一次性明文 + 复制 + 撤销确认弹窗，
  统计 6/4/2 随操作更新）、`/usage`（8 项真实数据、筛选 `/v1/predict` 后 9 条、
  空结果显示“所选范围内暂无调用记录。”、分页 20+8 且上一页回到同一条）、
  `/billing`（¥0.006374、25 条明细、分页 20+5）；侧栏账号取自 `/v1/auth/me`，
  退出后 `/usage` 302 回 `/login`；浏览器控制台无错误。
- 库内取证：`api_keys.key_hash` 为 64 位十六进制且不含明文；`api_calls` 与
  `pricing_rules` 通过 `pricing_rule_id` 固定版本；`usage_charges` 金额为 DECIMAL(20,6)。
- 隔离与并发取证（双账号，8020）：B 的汇总只含自身调用；`?api_key_id=<A 的 Key>` 对
  `/v1/usage/calls` 与 `/v1/billing/charges` 返回 `[]`；B 撤销 A 的 Key 为 404。请求体
  伪造 `usage` 被忽略，入库为真实分词 Token。6 个并行请求全部 200，新增 8 条调用与
  8 条费用行、`call_id` 无重复。日志调用仅输出 id/code/source，`print` 与日志中无
  password/secret/明文 token；库内非 64 位十六进制的 `key_hash`/`token_hash` 与非
  `$argon2id$` 前缀的 `password_hash` 行数均为 0。
- 2026-10-03 页面实测（8030，Playwright 无头 Chromium）：登录落地页、统计缺省上界截秒、
  受保护页面命中浏览器缓存、页面时间按本地时区渲染、空窗口金额位数、费用图纵轴刻度
  共六处缺陷修复后，39 项页面回归与 23 项筛选回归全绿；`/usage`、`/billing` 补上
  时间范围与每页条数筛选。以上只改前端与展示口径，接口字段与状态码未变；
  页面时间统一按 UTC 渲染并标注 UTC，金额固定补齐 6 位小数。
  与设计稿的可见差异及登录稿多出的「概览」入口记录在任务 §8.3，未静默实现。
- 2026-10-03 用户复现清单修复（8030 重启后复跑）：缺 `input_tokens` 由 200 改回 500
  `usage_unavailable`（状态码变更，用户明确要求；库内仍是 `failed`/`pending`、不入账）、
  登录失败计数改为单条 UPSERT 后 5 线程并发计满 5 次且无死锁、`from`/`to` 带时区偏移
  不再报 `TypeError`、`/keys` 与 `/usage` 的时间列表头标注 UTC。
  验证为 14 项后端复现（`TestClient`，不加载模型）+ 27 项筛选/时区 + 39 项页面回归全绿，
  静态门禁与 OpenAPI 14 路径复跑通过。这是行为变更而非纯展示改动，已记录在任务 §9。
- 待确认：Git 协作策略、完整依赖与模型 revision、业务验收、部署目标、
  性能/SLO、测试工具及简单任务阈值；会话有效期、限速阈值、密码规则、
  金额展示精度、统计时区、失败/超时计费策略与分页上限仍为本次采用值，未经产品确认。
