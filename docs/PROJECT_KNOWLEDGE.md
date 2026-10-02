# 项目事实、知识索引与现状审计

核查日期：2026-10-02。源码及运行环境为主要依据；版本与文件状态会变化，使用前复核。
本文件集中记录知识，归档在 `docs/`，不散落重复文档。

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

- 形态：单目录本地 HTTP 服务 + CLI，未见多模块、Worker、消息消费者或定时任务。
- `api.py` 是 ASGI 入口；`customer_service_test.py` 是复用的客服逻辑和 CLI 入口。
- `run-api` 是 zsh/Uvicorn 启动器，`run-laya` 是 Laya 命令行启动器。
- 当前 Python 3.12.5，Laya 0.3.23，FastAPI 0.142.2，Uvicorn 0.54.0，
  Pydantic 2.13.5，Torch 2.14.1，Transformers 5.18.0，HTTPX 0.28.1。
  来源：`.venv/bin/python` 和 `importlib.metadata.version`，不是依赖锁。
- 包管理：本机有 uv；`requirements-api.txt` 仅声明 `fastapi>=0.115,<1` 与
  `uvicorn>=0.30,<1`；没有项目完整依赖声明、锁文件或 pyproject。
- 已安装包一致性可用 `uv pip check --python .venv/bin/python --cache-dir .uv-cache`。
- 未见 DB、缓存服务、MQ、搜索、对象存储、迁移或 Schema。
- 文件持久化是 `.hf-cache` 模型缓存；另有 `.venv`、`.uv-cache`、`.idea`、
  `__pycache__`、`torchinductor_wangfei` 本机目录，不擅自删除。
- 未见 Docker、Kubernetes、反向代理、进程管理配置或 CI；运行方式是终端进程。
- 2026-10-02 按用户要求初始化 Git；`.gitignore` 排除虚拟环境、模型/工具缓存、
  IDE、字节码、日志及本地环境密钥文件。团队分支策略待确认。
- 没有自动化测试文件/配置；客服文件名含 test 但运行的是 CLI 推理。
- 未安装 pytest、ruff、mypy、build，也没有 formatter、Lint、打包或覆盖率配置。

## 架构与生命周期

HTTP → Pydantic 校验 → `api.py` 同步路由 → `threading.Lock` →
客服 `analyse` 或 `Router.predict` → Laya multilingual → JSON 响应。

`api.py` 从客服模块导入 Router 和 analyse，客服模块不依赖 API。
lifespan 在启动时创建 `Router(max_loaded=1)` 并加载 multilingual，保存至 app.state；
请求复用该实例。同步路由由框架在线程池中执行，推理锁把两类预测串行化。
模型加载失败会阻止应用启动。当前 lifespan 退出没有显式模型清理逻辑；
关机依赖 Uvicorn/进程回收，不能声称已实现自定义排空/取消策略。

`run-api` 设置 `HF_HOME` 为项目缓存、`HF_HUB_OFFLINE=1`、默认 `LAYA_DEVICE=mps`，
绑定 `127.0.0.1:8000`，单 worker；其尾部允许追加 Uvicorn 参数。
`api.py` 仅接受 mps/cpu；直接运行 uvicorn 不会自动设置离线变量。
客服模块通过 `setdefault` 设 HF_HOME；CLI 调用可新建 Router，API 则传入共享 Router。
无数据库事务或外部业务写操作；直接非离线启动可能由 Laya 检查/下载 HF 模型。

## 当前契约

| 方法与路径 | 请求 | 成功响应 |
| --- | --- | --- |
| GET `/health` | 无业务参数 | status、model、device |
| POST `/v1/customer-service/analyze` | message：1–8000 字符，禁止纯空白 | 客服分析对象 |
| POST `/v1/predict` | state、questions、可选 lang（默认 zh） | 原生 Laya answers、usage、routing 等 |

请求使用 JSON；无自定义 Header 或鉴权依赖，无分页/排序/过滤约定。
客服响应字段：message、category、category_name、category_probability、recommended_action、
priority、needs_human、signals、model。分类有 refund、technical_help、billing_question、
information、cancellation、other（来自 Laya triage 预设及脚本映射）。

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
没有统一业务码或响应外壳；错误结构并非完全统一。
`/docs`、`/redoc` 和 `/openapi.json` 为 FastAPI 当前默认文档路由。
无版本废弃策略；当前路径只使用 /v1，不推断已有多版本治理。

## 现状审计

P1 表示涉及未来对外暴露、资源耗尽或明显验证缺口；P2 为维护/复现性问题。
这是建议优先级，不是已确认的生产事故。

| 优先级 | 证据与问题 | 影响 | 建议（本次不实施） |
| --- | --- | --- | --- |
| P1 | api.py 无鉴权；run-api 默认 loopback | 改监听地址后任意可达调用方可用推理 | 外部暴露前确认认证、授权及限流 Spec |
| P1 | inference_lock 无排队截止/请求级推理超时 | 并发请求占线程排队，超时客户端不代表推理取消 | 明确队列上限、超时和取消策略并验证 |
| P1 | 仅字段字符校验，无请求体总字节/深度边界 | 超大或深嵌套 JSON 在校验前消耗资源 | 评估服务/代理身体积限制及边界样本 |
| P1 | 没有自动化测试，unittest discovery 为 0 | 契约、阈值和错误分支易回归 | 后续变更同步校验、规则及 HTTP 回归测试 |
| P2 | requirements-api.txt 非完整依赖，未锁版本 | 新环境不能仅靠此文件完整复现模型服务 | 明确完整依赖与锁定策略后再修改配置 |
| P2 | 已初始化 Git 并添加忽略规则；缓存和 IDE 目录仍在根目录 | 手工强制添加仍可能误跟踪本机文件 | 每次提交前审查暂存清单，避免 git add -f |
| P2 | logger.exception 与访问日志，未见脱敏策略/Request ID | 故障关联与隐私控制待确认 | 设计结构化诊断和脱敏规则，不记客户原文 |
| P2 | health 仅报告启动后状态；无模型功能探测 | 200 不证明后续推理始终可用 | 区分存活、就绪与功能探针并评估开销 |
| P2 | 无吞吐、P95/P99、内存或失败率报告 | 无法给出生产容量或可靠性承诺 | 待建立可复现冷/热启动及并发基线 |
| P2 | 概率及规则阈值有代码，无业务验收集 | 单条分类成功不证明普遍中文客服准确性 | 用合成/授权脱敏样本建立验收集 |
| P2 | lifespan 无显式退出动作，无部署配置 | 重启、排空、失败恢复要求未确定 | 确认运行环境与优雅退出验收 |
| P2 | run-laya/CLI 未强制离线，API 启动器强制离线 | 不同入口网络/缓存行为有差异 | 文档保持区分；如需统一先确定需求 |

未发现默认脚手架业务代码；不因 FastAPI 存在就假设有 DB、CORS 或权限。
43 个已安装包兼容性通过，不等于不存在未使用依赖；仅凭包列表无法确认可删对象。
README 的本机 URL 是服务运行时地址，不是外网失效链接。
当前无 SQL、上传、模板或自定义反序列化路径；无需生成不相关框架模板规则。

## 验证记录与待确认

- 2026-10-02：uv pip check 检查 43 包，安装包互相兼容。
- zsh -n 检查两启动器通过；导入 api 并生成 OpenAPI 3.1.0，三个路径存在。
- unittest discover 找到 0 个测试（退出非成功），不能记为全量测试通过。
- 初次审计时 git status/log 因非 Git 仓库失败；后续按用户要求初始化，
  提交前执行 Git diff 格式检查与暂存清单审查。
- 未配置 Lint、类型检查、构建/打包；不新增依赖来伪装完成这些检查。
- 本次为文档任务，不启动/重启服务，不发模型业务请求、不改依赖和配置。
- 文档归档：根目录保留 AGENTS.md 和 README.md，规则、知识、Spec 指南位于 docs/。
- 待确认：Git 协作策略、完整依赖与模型 revision、业务验收、认证、部署目标、
  性能/SLO、测试工具及简单任务阈值。
