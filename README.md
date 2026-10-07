# Laya 模型 API 与 API Key 管理平台

平台需求：[邮箱密码登录、Key 管理、调用统计与 Token 计费](docs/20261002-Laya平台-需求.md)。
价格为 1 元 / 100 万输入 Token。邮箱密码登录与注册、API Key 管理、推理鉴权、
调用记录、Token 计费与统计页面均已实现；失败与超时调用的计费规则仍待产品确认，
当前只对成功且产出原生 Token 用量的调用记账。

AI 开发入口：[AGENTS.md](AGENTS.md)；[规则索引](docs/AI_RULES.md)；
[项目事实与审计](docs/PROJECT_KNOWLEDGE.md)；[Spec 指南](docs/SPEC_GUIDE.md)。
根目录保留开发入口与使用说明，规则、知识和 Spec 文档归档在 `docs/`。

当前环境为 Python 3.12.5、Laya 0.3.23、FastAPI 0.142.2、Uvicorn 0.54.0、
MySQL 9.6.0、Node 22.22.3（2026-10-02 本机快照）。`requirements-api.txt` 声明 API、
鉴权与数据库驱动依赖，不是完整模型安装清单，也没有 Python 锁文件；前端有
`package-lock.json`。密钥删除、管理员权限和品牌配置有标准库 unittest 回归测试（`PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests`）；未配置 Lint 或类型检查。

## 目录结构

后端在 `backend/app`（入口 `app.main:app`），前端在 `frontend/`（`src/` 是页面与
`app.js`，`dist/` 是构建产物，由后端以 `/assets` 同源提供），
迁移 SQL 在 `backend/migrations/`。根目录 `run-api`、`run-laya` 与
`customer_service_test.py` 仍是入口脚本。详见
[任务文档](docs/20261002-Laya平台-任务.md)。

## 前置条件

登录功能需要本机 MySQL。在项目根目录创建 `.env`（已被 Git 忽略）：

```dotenv
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=laya_app
MYSQL_PASSWORD=<你的密码>
MYSQL_DATABASE=laya_platform
```

表结构在服务启动时按 `backend/migrations/` 的 `0001_auth.sql`、`0002_api_keys.sql`、
`0003_billing.sql`、`0004_api_key_deletion.sql`、`0005_user_admin.sql`、
`0006_platform_settings.sql` 顺序自动创建（幂等，含 `v1` 价格规则种子）。迁移账号需要
`CREATE`/`INDEX`/`REFERENCES` 与 `ALTER` 权限；DDL 与回滚脚本成对提供。

## 构建前端

页面样式使用 Tailwind CSS，需先构建，否则 `/login`、`/keys`、`/usage`、`/billing`
返回 500 提示未构建：

```bash
cd frontend && npm install && npm run build   # 产出 frontend/dist/
```

启动（复用 `.venv` 和 `.hf-cache` 中已安装的模型，默认 MPS）：

```bash
cd /Users/wangfei/study/laya
zsh run-api
```

CPU 启动：`LAYA_DEVICE=cpu zsh run-api`。使用 `Ctrl+C` 停止。
默认仅监听本机 `127.0.0.1:8000`，单进程加载一个模型，推理请求串行执行。
启动器使用离线缓存，不会在启动时下载模型。

接口文档：http://127.0.0.1:8000/docs
OpenAPI：http://127.0.0.1:8000/openapi.json（可导入 Postman）

## 登录与注册

浏览器访问 http://127.0.0.1:8000/login（未登录时 `/` 自动跳转，登录后落到 `/keys`）。
管理接口前缀 `/v1/auth`，写操作要求 `X-CSRF-Token` 与 `laya_csrf` Cookie 一致：

```bash
curl -s -c /tmp/j http://127.0.0.1:8000/login -o /dev/null   # 下发 CSRF Cookie
CSRF=$(grep laya_csrf /tmp/j | awk '{print $NF}')
curl -s -b /tmp/j -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"至少 8 位密码"}' \
  http://127.0.0.1:8000/v1/auth/register
curl -s -b /tmp/j -c /tmp/j -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"至少 8 位密码"}' \
  http://127.0.0.1:8000/v1/auth/login
curl -s -b /tmp/j http://127.0.0.1:8000/v1/auth/me
curl -s -b /tmp/j -H "X-CSRF-Token: $CSRF" -X POST http://127.0.0.1:8000/v1/auth/logout
```

密码用 Argon2id 哈希存储，会话只保存 Token 的 SHA-256，有效期 7 天。
同一邮箱 15 分钟内 5 次密码错误会锁定 15 分钟，返回 429。
错误邮箱与错误密码返回同一个 401 响应体，不透露账号是否存在。

## API Key 与统计

管理页：http://127.0.0.1:8000/keys、`/usage`、`/billing`（未登录跳转 `/login`）。
Key 接口前缀 `/v1/api-keys`，同样要求登录会话与 CSRF 令牌；库中只保存 Key 的
SHA-256，完整密钥只在创建响应里出现一次。创建时可带可选 `name`（≤60 字，只用于展示
与识别，不参与认证），列表与创建响应都会回传该名称。

```bash
curl -s -b /tmp/j -c /tmp/j -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d '{"name":"生产后端"}' \
  http://127.0.0.1:8000/v1/api-keys                     # 返回 secret，仅此一次
curl -s -b /tmp/j http://127.0.0.1:8000/v1/api-keys     # 脱敏列表（含名称）与数量汇总
KEY_ID=<上面返回的 id>
curl -s -b /tmp/j -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d '{"confirm":true}' http://127.0.0.1:8000/v1/api-keys/$KEY_ID/revoke
curl -s -b /tmp/j 'http://127.0.0.1:8000/v1/usage/summary?from=2026-10-01&to=2026-10-03'
curl -s -b /tmp/j 'http://127.0.0.1:8000/v1/billing/charges?limit=20'
```

已撤销密钥可通过页面确认删除，或 `DELETE /v1/api-keys/{id}`（会话与 CSRF）删除。成功返回 `{code:"ok"}`；可用密钥返回 409，他人或不存在返回 404。删除后列表隐藏，历史调用与费用保留，重复删除幂等。详见[删除需求](docs/20261007-撤销密钥删除-需求.md)。

统计接口按 UTC 半开区间 `[from, to)` 过滤，只返回当前用户名下的数据；明细用
`cursor` 做 keyset 分页，响应带 `next_cursor`/`has_more`。汇总与明细同源，可逐条对账。

## 客服分析

推理接口只接受 `Authorization: Bearer <API Key>`，缺失、无效或已撤销返回 401，
且不会加载模型。登录会话不能代替 Key。

```bash
curl http://127.0.0.1:8000/v1/customer-service/analyze \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message":"我被重复扣款了，请马上退款，否则取消服务。"}'
```

响应包含 `category`、`category_probability`、`priority`、`needs_human`、
`recommended_action` 和 `signals`。分类与风险信号来自模型，优先级、
人工分流和建议动作来自客服业务规则。响应头 `X-Request-Id` 是本次调用记录的主键，
与统计明细中的“请求标识”一致。

## 自定义结构化预测

```bash
curl http://127.0.0.1:8000/v1/predict \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"state":{"message":"请帮我退款"},"lang":"zh","questions":{"refund_requested":{"type":"noul","instructions":"客户是否要求退款？"}}}'
```

`questions` 的每个问题支持三种类型：

- `choice`：`criteria` 是分类名称到描述的对象，返回 `choice` 和 `probabilities`。
- `score`：`criteria` 是从低到高的等级描述列表，返回从 0 开始的连续 `score`。
- `noul`：返回表示“是”的概率 `noul`，可用 0.5 作为业务阈值。

返回原生 Laya 结果，主要读取 `answers` 和 `routing`。模型固定为 `multilingual`。
参数校验失败返回 HTTP 422，推理内部错误返回 HTTP 500，具体错误记录在终端。

计费以模型返回的原生 `usage.input_tokens` 为准，金额用 Decimal 按
`Token ÷ 1,000,000 × ¥1` 计算并保留 6 位小数；每次调用固定当时的价格版本，
`usage_charges` 对 `call_id` 唯一，避免重复扣费。拿不到用量信息的失败调用标记为
计费待确认（`billing_status=pending`），其它失败与中断按当前策略标记为不计费。

健康检查：`curl http://127.0.0.1:8000/health`。
本服务执行分类和评分，不生成聊天回复。

## 管理员后台与平台品牌

`users.is_admin` 默认为 0，注册不能升权。登录、注册和 `/v1/auth/me` 的 `user` 新增布尔字段
`is_admin`；管理员登录或访问根路径进入 `/admin`，普通账号进入 `/keys`。
管理员可在 `/admin/settings` 设置名称、简介、Logo，在个人控制台可返回平台管理。
首次使用前须明确指定已注册的管理员账号，再由有权限的数据库操作人员按邮箱将
`users.is_admin` 设为 1；本机已按用户明确指定完成首个管理员赋权，管理员身份不由迁移自动设置。角色每次从数据库读取，降权后原会话
的下一次管理请求即被拒绝。

- `GET /v1/admin/overview?from=&to=`：管理员会话，最多 366 天，返回平台存量指标和 UTC 日趋势。
  账号总数包含所有账号，可用密钥排除已撤销、已删除及停用账号；历史费用保留。
- `GET /v1/platform/branding`：公开的名称、简介、Logo 地址，供页面品牌展示。
- `GET /v1/platform/logo`：PNG 图片，未设置时 404，页面显示默认 Logo。
- `PUT /v1/admin/settings`：管理员会话 + CSRF，JSON `{name,description,logo_data_url}`。
  名称 1–60 字，简介最多 200 字；Logo 为 PNG/JPEG/WebP 的 base64 data URL，解码后最多
  2 MB，尺寸最多 4096 × 4096；null 保留原图，空字符串恢复默认。请求总大小最多 3 MB。

新增依赖 Pillow（本机验证 12.3.0，声明 `>=11,<13`），只用于 Logo 解码验证与转码；
图片验证后缩放至最多 512px 并重新编码为 PNG，去除元数据。配置保存在 MySQL 单行表
`platform_settings` 中，保存成功后刷新各页面读取新品牌；浏览器不负责存储全局配置。
迁移/回滚脚本成对提供，先回滚代码再回滚结构；回滚配置表会丢失品牌定制，不自动执行。
已有服务须重新加载后端代码才能使用新增接口，不要重复启动模型进程。
