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

新会话必须提供 `user_id`：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/chat" `
  -H "Content-Type: application/json" `
  -d '{"user_id":"demo-user","message":"帮我找适合小型科技服务企业的尽调报告"}'
```

续聊带回 `session_id`；`user_id` 可省略，若提供则必须与会话所属用户一致：

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
- `GET /api/v1/ops/conversations`
- `GET /api/v1/ops/metrics`
- `/api/v1/ops/model-profiles` 下的创建、修改、测试、激活和删除接口

筛选、统计和比赛问答不再提供独立接口。用户可以直接发送“筛选科学研究和技术服务业报告”“现在有多少篇报告”或“比赛要求是什么”。比赛回答当前由大模型生成并附带非官方资料免责声明。

推荐会先返回 Top 3，多维筛选有一个及以上条件时会立即返回全部 AND 命中结果。可选细化条件通过统一聊天接口提交：

```json
{
  "session_id": "ses_xxx",
  "action": {
    "type": "apply_refinement",
    "selections": [
      {"tag_name": "行业分类", "value": "制造业"},
      {"tag_name": "企业规模", "value": "小微企业"}
    ]
  }
}
```

可发送 `skip_refinement` 暂不补充，或在零结果时发送 `remove_tag` 放宽条件。关联案例通过统一聊天接口调用：

```json
{
  "session_id": "ses_xxx",
  "action": {"type": "related_reports", "report_id": "rpt_xxx"}
}
```

“猜你想问”每批返回3个 `{text, intent}` 项；刷新时传回 `previous_batch_id`，服务会优先展示上一批遗漏的第四项功能并避免重复。

## 报告数据规则

`data/**/*.json` 是报告数据的唯一事实来源。每个文件可包含单份报告对象或报告数组。服务器启动时先校验全部文件，再在单一事务中替换 `reports` 和 `report_tags`；任一文件无效或报告 ID 冲突都会导致启动失败。

运行期间新增、修改或删除 JSON 不生效，必须重启服务器。重建报告表不会删除 `sessions`、`messages`、`session_tags` 和 `model_profiles`。

## 模型配置

模型活动配置优先级为：SQLite 当前激活配置，其次是 `.env`。运营端新配置必须先通过连通性和结构化 JSON 测试才能激活。激活使用原子切换，失败会保留原活动模型。接口、页面和日志都不会返回 API Key 明文或数据库密文。

## 测试

```powershell
pytest -m "not live"
Set-Location frontend
npm test
npm run build
```

真实浏览器验收使用 Playwright CLI，截图保存在 `output/playwright/`。Docker 不在本轮测试范围内。
