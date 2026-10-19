# 规则索引与项目约束

## 加载与维护

| 文件 | 职责 | 适用任务 |
| --- | --- | --- |
| [AGENTS.md](../AGENTS.md) | 入口、红线、命令 | 所有修改 |
| 本文件 | 长期规则、冲突顺序、质量门禁 | 开发、修复、审查 |
| [PROJECT_KNOWLEDGE.md](PROJECT_KNOWLEDGE.md) | 当前实现、契约、风险与证据 | API、模型、运行与审计 |
| [SPEC_GUIDE.md](SPEC_GUIDE.md) | 单次需求、设计、任务文档规则 | 复杂变更 |
| [平台需求](20261002-Laya平台-需求.md) | 已确认目标、价格与待确认业务细则 | 登录、Key、鉴权、统计与计费 |
| [README.md](../README.md) | 安装现状与调用方法 | 本机使用 |

先读索引，再加载任务涉及章节，不读取整个模型缓存或第三方源码代替项目证据。
冲突顺序：当前用户明确要求 → 已确认 Spec → 本项目规则 → 项目知识 → 代码惯例。
这个顺序不允许静默覆盖：列出冲突位置、影响、可选方案并明确实际采用方案。
修改长期约束时同步本索引；事实变更同步知识；接口用法变更同步 README。
更新版本快照要记录日期和验证命令，不能把安装版本说成锁定版本。

## 范围与架构

- 平台目标为邮箱密码登录、API Key 管理与 Token 计费；当前已实现登录、注册、会话、
  登录限速、API Key 生命周期、Bearer 推理鉴权、调用记录、Decimal 计费、统计查询，
  以及登录/Key 管理/调用统计/费用统计四个个人页面与管理员总览/配置/用户管理页面。失败与超时调用的计费规则仍待产品确认。
- 登录写操作必须带 Double-Submit CSRF，会话使用 HttpOnly Cookie；对外暴露仍待安全 Spec。
- 明确需求要求的范围才扩展；不主动引入消息队列、缓存服务或设计未覆盖的数据层。
- 代码按 [架构设计](20261002-Laya平台-设计.md) 组织：后端在 `backend/app`
  （`api/v1`、`core`、`db`、`schemas`、`services`），前端在 `frontend/`，
  启动器与客服 CLI 留在根目录。不建空壳层，不提前创建未实现的模块。
- 前端按 [工程结构设计](20261018-工程结构整理-设计.md) 组织：HTML 仅放
  `src/pages/templetes/`，页面模块在 `pages/`，公共 HTTP/lib/UI/console 在 `shared/`，
  分职责 CSS 在 `styles/`。页面可依赖公共模块，公共模块不得反向依赖页面。
  模块导入不得自动绑定事件或请求；页面显式初始化一次。品牌读取失败不阻断登录。
  不增加框架/路由/store 空壳；确有重复或独立测试价值才抽取新模块。
- 构建只发布 HTML、运行时 JS、CSS 和实际静态资源，不发布 tests/scripts/私有配置。
  模板源码集中不改变 dist 根级 HTML 文件名；watch 必须覆盖嵌套 HTML/JS/CSS。
- 用户已确认[彻底分离](20261018-前后端分离-设计.md)：后端不设 web/，不读取 dist、不返回业务页面。
  前端独立静态托管并同源代理 API，不新增宽泛 CORS。首次 CSRF、根路径导航和角色导航在前端；
  所有管理/个人 API 仍必须服务端鉴权，公开页面壳不等于数据公开。
- API 容器不包含 Node 或前端产物；Nginx 前端和 Python 后端独立构建。
  Compose 的 app/db 禁止发布宿主端口；仅受控边缘代理覆盖转发头，内部 API 才可配置代理信任。
  禁止重试/缓存推理请求，保持 Cookie、CSRF、请求 ID、原状态码和浏览器入口的重定向地址。
- API 可依赖客服模块和 Laya；客服模块不得反向依赖 API，避免循环引用。
- 业务分流使用既有阈值；改阈值需要说明验收样本和影响，不凭模型结果发明政策。
- 新抽象必须有重复逻辑、真实替换需求或独立测试价值；不为一次调用建空层。
- 后端职责按[职责修复设计](20261018-后端职责修复-设计.md)：路由不互相依赖，
  共用 HTTP 协调归 api/inference_support.py；schemas 不依赖 services/db/api。
  integrations 不依赖 services/db/api/main，传输不掌握业务事务；结算与恢复共用
  services/inference.py 的公开内部事务接口。品牌与管理员总览分别归属独立服务。
  db/migrations.py 只执行已有 DDL；启动仍执行迁移，本轮未改变部署策略。
- 模型生命周期由 lifespan 管理，路由复用实例；禁止逐请求加载模型。
- 推理保持同步并受同一线程锁保护；不要把阻塞推理直接放进异步处理函数。
- 持久化为 MySQL `laya_platform`，当前十三张表：设计 §2 的 `users`、`user_sessions`、
  `api_keys`、`pricing_rules`、`api_calls`、`usage_charges`，加上实现补齐的
  `login_throttle` 和 `platform_settings`；`model_connection` 只存管理员固定上游的非秘密配置，`admin_audit_events` 保存管理操作审计，`request_rate_windows` 只存请求计数临时窗口。DDL 唯一来源是 `backend/migrations/`（`0001_auth.sql`、
  `0002_api_keys.sql`、`0003_billing.sql`、`0004_api_key_deletion.sql`、`0005_user_admin.sql`、`0006_platform_settings.sql`、`0007_model_gateway.sql`、`0008_admin_audit.sql`、`0009_request_rate_windows.sql`、`0010_success_receipts.sql`、`0011_request_idempotency.sql`），成功回执表`inference_success_receipts`只保存可信完成事实/计量，`request_idempotency`只保存user范围Key及请求摘要，不保存正文。不虚构未设计的表。`api_calls` 与
  `usage_charges` 是账务事实，不做原地改写。
- 数据库凭据只放根目录 `.env`（已忽略），不提交、不写日志。

## 接口与编码

- 以 `backend/app/schemas` 的 Pydantic 模型和生成 OpenAPI 为契约源，入口 `app.main:app`。
- 管理类成功内容通过 `api/responses.py` 的 `success()` 显式构造，保持原平铺字段；
  201、Cookie 和响应头仍由路由处理。不得用中间件包装推理/OpenAI 兼容输出、图片或 health。
- 简单公开错误通过 `api/errors.py` 显式构造，保留原异常类型分支、状态码与响应头，
  不增加 catch-all。有限正文读取通过 `api/request_body.py`，调用方保留权限/CSRF/解析顺序
  和各自字节上限。管理服务仅返回业务数据，code 归 API；统计 range 使用 utc_range，
  上游 parse_range 负责 UTC 归一，不能借格式化合并跨度策略。
- 保持现有推理路径、JSON 字段和 200/422/500 语义；记账只追加 `X-Request-Id` 响应头，
  不改业务字段。推理接口仍无统一响应包裹或业务码。
- 新增的 `/v1/auth/*`、`/v1/api-keys/*`、`/v1/usage/*`、`/v1/billing/*` 使用平铺
  `{"code","message"}` 错误体；422 仍保持 FastAPI `detail` 结构。两类结构并存是现状，
  冻结前不得回头改动推理接口。
- 金额与单价只由服务端用 Decimal 计算，页面只展示结果；统计查询必须带认证用户范围，
  Key ID 与请求 ID 只是资源定位符，不构成权限。
- `choice`、`score`、`noul` 分别保持分类、零起始等级期望值和真概率语义。
- 客服 `priority` / `needs_human` 是规则输出，不冒充模型直接预测。
- 遵守当前 Python 类型注解、snake_case、四空格缩进及 Pydantic v2 用法。
- 扩展输入校验时覆盖空白、边界、非法类型与复杂对象；不删除校验通过检查。
- 异常在 HTTP 边界转换；500 保留服务日志，禁止吞错或返回伪成功。
- 记录诊断上下文时不要输出客户原文、Token 或内部敏感配置。
- 环境变量由启动脚本与生命周期读取；模型缓存位置参见知识文档。
- `.venv`、第三方包、缓存和生成 OpenAPI 不是日常编辑目标。
- 不大范围无关格式化，不保留注释掉的废弃代码。
- 当前未配置 formatter / Lint / 类型检查（`.venv` 内无 ruff、mypy）；不能新增命令并宣称
  既有门禁。引入门禁工具前先写明需求与具体执行命令。

## 测试与验证

- 已有 `backend/tests` 标准库 unittest 密钥删除、管理员权限与品牌配置回归套件，`customer_service_test.py` 是 CLI 演示，不是测试。
- 后端测试按 unit/contract/integration/e2e 分类，support 只含测试辅助；测试模块不裸导入
  另一个 test 文件。根路径统一用 `tests.support.paths.ROOT`，不要依赖文件深度。
  默认命令保持递归发现；分类执行使用 `-t backend` 保持包导入一致。
- 前端 `npm run build` 后执行 `npm test`（Node 内置测试，无新增依赖）；它验证纯逻辑和
  模块/产物契约，不能替代 `tests/browser/smoke.mjs` 的真实浏览器交互验证。
- 新功能覆盖正常、非法、边界输入及错误映射，用可复现命令记录验证。鉴权与多租户变更
  必须验证跨用户隔离、撤销即时生效与队列期间失效（拿到锁后重检），不能只测正常路径。
- Bug 流程：复现 → 失败测试 → 根因 → 最小修复 → 相关验证 → 全量已有回归。
- 纯校验与业务阈值应做 Unit 验证；HTTP 与假 Router 做 Component/Contract 验证。
- 真实模型做 Integration 验证；启动到 HTTP 的整体链路做 End-to-End 验证。
- 假模型测试与真实模型测试要明确区分，不用假模型证明推理准确性。
- 避免重复下载和随机联网；真实模型用缓存，概率验收使用合理范围而非完全相等。
- 并发、超时、失败注入按变更范围验证；样本使用合成文本，不持久化客户隐私。
- 无覆盖率门槛；新增测试工具/依赖前写明需求和具体执行命令。
- 当前门禁是 `uv pip check`、`zsh -n run-api run-laya`、Python 语法解析、OpenAPI 生成检查
  与前端 `npm run build`（见 AGENTS）；另有 `PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests`；无 Lint、覆盖率与类型检查配置。
- 不存在的全量测试、类型检查及打包应标记“未配置”，不得当成通过。

## 安全、可靠性与性能

- 默认仅监听 loopback；引入公网或局域网暴露前创建安全与部署 Spec。
- 登录会话使用 HttpOnly Cookie 与 Double-Submit CSRF；管理接口只认会话，推理接口
  只认 `Authorization: Bearer <API Key>`（缺失/无效/已撤销 401，停用账号 403），
  登录会话不能代替 Key。库中只存 Key 与 Session 的 SHA-256，完整 Key 只在创建响应
  出现一次；页面与统计只输出脱敏标识。不把本机监听等同于鉴权。
- 调用终态、用量与费用在同一短事务内写入；拿不到用量时标记计费待确认，
  记账失败不得对外返回伪成功。数据库事务不跨推理持有。
- Token用量严格校验整数（排除bool）、非负及范围；终态和已知用量不得冲突覆写。同调用相同成功事实重复结算返回原费用，不另插费用；恢复默认只读，显式--apply只按可信成功回执及原价格恢复（已确认可对原HTTP500调用补账）。不能仅凭running、年龄或已知用量收费。
- 可选Idempotency-Key在同用户所有Key/入口共享，摘要占位与accepted原子提交；重复409原调用ID，不回放成功回复、不重跑模型、不自动删除记录。响应必须先可JSON编码才保存成功回执，后处理失败保留有效用量但不收费。
- 固定服务模型，禁止把用户输入当作 Shell、文件路径或模型下载地址执行。
- 评估身体积、嵌套深度、排队时间和线程占用，不把字符上限等同于完整限流。
- 当前有日志和健康端点，无自定义重试、熔断、指标、Tracing 或告警。
- 不擅自增加推理重试；重试会增加排队和资源占用。
- 禁止多 worker/移除锁的盲目优化；必须评估独立进程重复加载与内存峰值。
- 用户限流默认关闭；RPM按UTC固定分钟持久化，在途名额覆盖排队到结算并finally释放。拒绝不记调用/费用，数据库失败拒绝准入，只清理24小时前临时窗口。不是Token硬配额。
- 待建立性能基线：固定模型、版本、设备、输入、并发和冷/热启动状态，记录吞吐、
  平均延迟、P95/P99、失败率与内存；不能把单次成功推理当容量结论。
- 模型/设备/依赖、并发策略、输入上限或日志量改变后用可比参数重新测量。
- 新增生产依赖需评估来源、兼容、安全、复现和回滚；更新依赖不能只改版本说明。

## 协作与审查

- Git 于 2026-10-02 按用户要求初始化；尚无团队分支或合并惯例。
- Conventional Commits 仅为建议，团队确认前不称为既有规范。
- 一次修改聚焦一个目标，同步契约、测试和文档，不夹带清理。
- Review 检查：范围、契约、阈值、模型加载、锁、错误日志、输入边界、验证证据。
- 未明确要求不得提交；无 Git 时说明无法执行 diff/历史检查，不自动初始化。

## 管理员权限与公开品牌

- `users.is_admin` 是服务端角色事实，默认 false，注册/浏览器参数不能赋权；首个管理员必须由用户明确指定。
- 首个管理员运维入口 `python -m app.manage init-admin --email` 使用指定邮箱；不隐式提升普通用户、不重新激活停用账号、不修改已有密码，禁止将口令传入命令行参数。
- 容器默认只绑定宿主 loopback；真实部署不得使用 `docker compose down -v`。容器测试只有显式 opt-in，随机隔离项目的合成数据才可自动清理。
- 管理员后台和 `/v1/admin/*` 依赖当前会话角色，普通用户 403、未登录接口 401；品牌写入要求 CSRF。
- 管理员平台聚合使用独立查询；既有个人统计仍带 user_id 范围，禁止移除。
- `/admin/users` 只管理普通用户状态，不修改管理员角色或状态；状态/Key实际变更与审计共同提交，重复操作不写新审计。停用同时撤销会话，登录发放会话前锁定复核当前状态。
- 管理员 Key 列表含软删除历史，仅输出脱敏标识；审计原因不存密码、完整 Key 或客户原文，历史调用与费用不因管理操作删除。
- 公开品牌接口只输出名称、简介、Logo 地址/图片，不扩展为系统配置或敏感参数接口。
- Logo 经 Pillow 校验、限大小/尺寸和重新编码，拒绝 SVG 与任意远程 URL；名称/简介只作为文本渲染。
