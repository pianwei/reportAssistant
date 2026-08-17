# 尽调报告助手

FastAPI + Vue 3 的尽调报告统一对话应用。案例推荐、多维筛选、数据统计和比赛问答都通过 `/api/v1/chat` 自动识别意图并路由。移动端入口为 `/`，运营管理端为 `/ops`。

## 环境准备

- Python 3.11+
- Node.js 20+
- Chrome 130 或更高版本

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

编辑 `.env`，填写模型地址、名称和 API Key。服务会自动读取项目根目录的 `.env`，操作系统环境变量优先级更高。`.env` 已被忽略，禁止将真实密钥写入 `.env.example` 或前端代码。

MySQL 数据库需预先创建，并在 `.env` 中配置：

```dotenv
DATABASE_URL=mysql://due_diligence:经URL编码的密码@mysql.bank.local:3306/due_diligence?charset=utf8mb4
```

应用启动时自动创建和升级业务表，因此数据库账号首次启动需具有 `CREATE`、`ALTER`、`INDEX`、`REFERENCES`、`SELECT`、`INSERT`、`UPDATE`、`DELETE` 权限。密码中的 `@/:#%` 等特殊字符必须进行 URL 编码。

运营端保存 API Key 前还必须配置 Fernet 主密钥：

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

将结果填入 `.env` 的 `MODEL_CONFIG_MASTER_KEY`。该主密钥不能写入数据库或交给前端。

## 前端开发与生产构建

```powershell
Set-Location frontend
npm install
npm run dev
```

开发服务器默认将 `/api` 代理到 `http://127.0.0.1:8000`。

生产运行前构建前端：

```powershell
Set-Location frontend
npm run build
Set-Location ..
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

访问地址：

- 移动助手：`http://127.0.0.1:8000/`
- 运营平台：`http://127.0.0.1:8000/ops`
- OpenAPI：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`

运营端当前没有登录鉴权，仅允许部署在可信内网。接入公网前必须增加认证和权限控制。

## curl 调用

新会话必须提供 `user_id`，并固定传入空的 `session_id`：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/chat" `
  -H "Content-Type: application/json" `
  -d '{"user_id":"demo-user","session_id":"","message":"帮我找适合小型科技服务企业的尽调报告"}'
```

续聊带回服务端返回的 `session_id`；`user_id` 可省略，若提供则必须与会话所属用户一致。`session_id` 是固定必传字段，新会话可传空字符串或 `null`：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/chat" `
  -H "Content-Type: application/json" `
  -d '{"session_id":"ses_xxx","message":"申请300万元流动资金贷款"}'
```

常用接口包括：

- `GET /api/v1/ui/bootstrap?user_id=...`
- `POST /api/v1/suggestions`
- `GET /api/v1/users/{user_id}/conversations`
- `GET /api/v1/conversations/{session_id}`
- `GET /api/v1/reports/{report_id}`
- `GET /api/v1/ops/conversations`（支持 `user_id`、`keyword`、`feature` 和 `days=1|3|7|30`）
- `GET /api/v1/ops/conversations/export`（按相同条件导出全部会话消息 CSV，不受列表分页限制）
- `GET /api/v1/ops/metrics`
- `/api/v1/ops/model-profiles` 下的创建、修改、测试、激活和删除接口

筛选、统计和比赛问答不再提供独立接口。用户可以直接发送“筛选科学研究和技术服务业报告”“现在有多少篇报告”或“比赛要求是什么”。比赛回答当前由大模型生成并附带非官方资料免责声明。

多轮问答由 `session_id` 串联。意图识别只使用同一会话最近 5 条用户问题，不读取助手回答；历史问题按时间从旧到新赋予 1～5 的递增权重，本轮问题始终具有最高优先级。前端会保存当前 `session_id`，点击右上角“＋”会清除它并开始新会话。

数据统计会从当前启动实例的全部报告生成列式全量标签 JSON 快照：报告 ID 数组与每类标签值数组按位置一一对应。报告总数、标签总数和分布由 MySQL 精确聚合；所有条件统计统一由当前激活模型一次分析完整快照并返回全部匹配报告 ID，后端校验 ID 后回填报告信息，不接受快照中不存在的报告 ID。模型连接、上下文或结构化输出失败时返回明确错误，不会把分析失败伪装成零结果。

案例推荐与多维筛选采用相同的引导卡、示例问题和对话输入交互，并共享同一 `session_id` 下的已收集标签；没有明确功能词的后续消息会追加或更新字段，并立即按当前模式返回结果。推荐按匹配度返回 Top 3，多维筛选按全部标签条件精确筛选并返回所有命中报告。报告匹配结果的衍生问题会额外提供“新筛选”；点击后清空当前标签，只回复“你有什么其他想要了解的尽调报告吗？”，不立即返回报告。关联案例通过统一聊天接口调用：

有明确标签条件时，推荐匹配分和多维筛选完全使用本地规则计算，不调用大模型评分。规则针对未规范化标签兼容括号说明、固定同义词、企业规模分级、布尔描述、授信品种、担保方式、申请性质、所有制性质、文本包含/字符相似度以及金额点值和区间重叠。大模型仅用于意图识别和从用户消息中抽取查询标签。

```json
{
  "session_id": "ses_xxx",
  "action": {"type": "related_reports", "report_id": "rpt_xxx"}
}
```

“猜你想问”每批返回3个 `{text, intent}` 项；刷新时传回 `previous_batch_id`，服务会优先展示上一批遗漏的第四项功能并避免重复。

“你好”“您好”“你能做什么”等问候使用固定能力介绍，不调用模型。超出尽调报告、报告统计和比赛范围的问题统一礼貌拒绝；比赛问答必须具有明确的比赛上下文。

## 报告数据规则

`data/**/*.json` 是报告数据的唯一事实来源。每个文件可包含单份报告对象或报告数组。服务器启动时先校验全部文件，再在单一事务中替换 `reports` 和 `report_tags`；任一文件无效或报告 ID 冲突都会导致启动失败。

运行期间新增、修改或删除 JSON 不生效，必须重启服务器。重建报告表不会删除 `sessions`、`messages`、`session_tags` 和 `model_profiles`。

## 模型配置

模型活动配置优先级为：MySQL 当前激活配置，其次是 `.env`。运营端新配置必须先通过连通性和结构化 JSON 测试才能激活。激活使用原子切换，失败会保留原活动模型。接口、页面和日志都不会返回 API Key 明文或数据库密文。

## 测试

后端数据库测试会为每个用例创建独立的临时 MySQL 数据库。测试账号需具有
`CREATE DATABASE` 和 `DROP DATABASE` 权限：

```powershell
$env:MYSQL_TEST_ADMIN_URL="mysql://root:经URL编码的密码@127.0.0.1:3306/mysql?charset=utf8mb4"
pytest -m "not live"
Set-Location frontend
npm test
npm run build
```

未设置 `MYSQL_TEST_ADMIN_URL` 时，MySQL 集成测试会跳过。真实浏览器验收使用 Playwright CLI，截图保存在 `output/playwright/`。
