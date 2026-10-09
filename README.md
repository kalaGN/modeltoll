# Laya

模型 API、API Key 管理与 Token 计费平台。支持本地 Laya 和外部兼容模型，提供登录、调用与费用统计、管理员总览、品牌配置及用户管理。

![平台配置界面预览（示例）](docs/platform-settings-preview.jpg)

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

使用已安装且缓存的本地 Laya 模型时，运行 `zsh run-api`。
登录地址：`http://127.0.0.1:8000/login`；接口文档：`http://127.0.0.1:8000/docs`。

## 验证

```bash
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests
npm --prefix frontend run build
```

## 文档

- [使用指南](docs/使用指南.md)：配置、部署、管理员初始化和 API 示例。
- [平台需求](docs/20261002-Laya平台-需求.md) · [自部署计划](docs/20261008-自部署平台-任务.md)
- [开发入口](AGENTS.md) · [项目知识](docs/PROJECT_KNOWLEDGE.md)
