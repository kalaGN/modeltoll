# Laya

[简体中文](README.md) | [English](README.en.md)

模型 API、API Key 管理与 Token 计费平台。支持本地 Laya 和外部兼容模型，提供登录、调用与费用统计、管理员总览、品牌配置及用户管理。

![平台配置界面预览（示例）](docs/platform-settings-preview.jpg)

## 用户请求限流

默认关闭；同一用户的全部 API Key 和三个推理接口共享额度。启用示例：

```bash
LAYA_USER_RPM=60 LAYA_USER_MAX_INFLIGHT=1 zsh run-api
```

容器部署把两个变量放入私有 `.env.deploy` 并重建应用容器；不要提交真实密码。
`LAYA_USER_RPM` 范围0–100000，`LAYA_USER_MAX_INFLIGHT` 范围0–1024，0关闭对应限制，非法值拒绝启动。
RPM 是 MySQL UTC 固定分钟预算，不是滚动60秒；分钟边界附近可能短时间接受两倍额度。
通过准入即占一次 RPM，后续模型或记账失败不退回；非法输入、鉴权失败、模型未配置及限流拒绝不扣次数。
在途名额覆盖排队、执行和结算，仍需单进程单 worker，不会增加模型并行度。
超限返回429及 `Retry-After`，业务码 `rate_limit_exceeded` / `concurrency_limit_exceeded`；计数数据库故障返回503 `rate_limit_unavailable`。
拒绝不产生调用或费用记录；重启保留同一分钟RPM，在途数随进程重启清空。
只清理24小时前的临时窗口，不清理账务历史。这不是 Token 硬配额。
关闭或回滚先设两个值为0并重启；停用新代码后才能人工执行0009表回滚。

## Docker 部署

需要 Docker Engine 和 Compose v2；容器仅使用外部模型模式。
复制 `.env.example` 为 `.env.deploy`，填写数据库密码，按需设置端口。

```bash
cp .env.example .env.deploy
# 编辑 .env.deploy 后执行
docker compose --env-file .env.deploy up -d --build --wait --wait-timeout 180
docker compose --env-file .env.deploy exec app python -m app.manage migrate
docker compose --env-file .env.deploy exec app python -m app.manage init-admin --email YOUR_EMAIL
```

管理员密码交互输入。打开 `http://127.0.0.1:APP_PORT/login`，在平台配置中连接上游模型。
默认仅监听本机；`.env.deploy` 不要覆盖已有 `.env`。

## 本机运行

需要 MySQL、Python 虚拟环境及 Node.js；数据库凭据放在 `.env`。

```bash
uv pip install --python .venv/bin/python -r requirements-api.txt
npm --prefix frontend ci
npm --prefix frontend run build
LAYA_RUNTIME=external zsh run-api
```

另一个终端运行 `npm --prefix frontend run dev`，启动独立前端并代理 API。

使用已安装且缓存的本地 Laya 模型时，运行 `zsh run-api`。
本机登录：`http://127.0.0.1:5173/login`；接口文档：`http://127.0.0.1:8000/docs`。
容器由独立 Nginx 前端提供 `APP_PORT` 入口，Python API 不包含页面。

## 验证

```bash
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests
npm --prefix frontend run build
npm --prefix frontend test
```

## 文档

- [后端 ORM 分层与验证](docs/20261019-ORM分层-设计.md)：Model、Repository、Service 和事务边界。
- [使用指南](docs/使用指南.md)：配置、部署、管理员初始化和 API 示例。
- [平台需求](docs/20261002-Laya平台-需求.md) · [自部署计划](docs/20261008-自部署平台-任务.md)
- [开发入口](AGENTS.md) · [项目知识](docs/PROJECT_KNOWLEDGE.md)
