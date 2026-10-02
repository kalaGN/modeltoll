# Laya 模型 API 与 API Key 管理平台

平台需求：[邮箱密码登录、Key 管理、调用统计与 Token 计费](docs/20261002-Laya平台-需求.md)。
价格为 1 元 / 100 万输入 Token；管理与计费功能尚未实现，下文是现有模型 API 用法。

AI 开发入口：[AGENTS.md](AGENTS.md)；[规则索引](docs/AI_RULES.md)；
[项目事实与审计](docs/PROJECT_KNOWLEDGE.md)；[Spec 指南](docs/SPEC_GUIDE.md)。
根目录保留开发入口与使用说明，规则、知识和 Spec 文档归档在 `docs/`。

当前环境为 Python 3.12.5、Laya 0.3.23、FastAPI 0.142.2、Uvicorn 0.54.0
（2026-10-02 本机快照）。`requirements-api.txt` 只声明 API 依赖，
不是完整模型安装清单；没有锁文件、自动化测试套件或构建配置。

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

## 客服分析

```bash
curl http://127.0.0.1:8000/v1/customer-service/analyze \
  -H 'Content-Type: application/json' \
  -d '{"message":"我被重复扣款了，请马上退款，否则取消服务。"}'
```

响应包含 `category`、`category_probability`、`priority`、`needs_human`、
`recommended_action` 和 `signals`。分类与风险信号来自模型，优先级、
人工分流和建议动作来自客服脚本中的业务规则。

## 自定义结构化预测

```bash
curl http://127.0.0.1:8000/v1/predict \
  -H 'Content-Type: application/json' \
  -d '{"state":{"message":"请帮我退款"},"lang":"zh","questions":{"refund_requested":{"type":"noul","instructions":"客户是否要求退款？"}}}'
```

`questions` 的每个问题支持三种类型：

- `choice`：`criteria` 是分类名称到描述的对象，返回 `choice` 和 `probabilities`。
- `score`：`criteria` 是从低到高的等级描述列表，返回从 0 开始的连续 `score`。
- `noul`：返回表示“是”的概率 `noul`，可用 0.5 作为业务阈值。

返回原生 Laya 结果，主要读取 `answers` 和 `routing`。模型固定为 `multilingual`。
参数校验失败返回 HTTP 422，推理内部错误返回 HTTP 500，具体错误记录在终端。

健康检查：`curl http://127.0.0.1:8000/health`。
本服务执行分类和评分，不生成聊天回复。
