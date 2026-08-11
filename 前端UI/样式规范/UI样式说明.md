# 立功竞赛助手前端 UI 实现说明

本文档与 2026-08-11 已部署的 Xanadu UI 版本同步，线上对照地址为
<https://pianwei.shadlc.net/due-diligence/>。

## 1. 技术栈与入口

- Vue 3 Composition API
- TypeScript
- Vue Router（HTML5 history）
- Vite 6
- 应用入口：`源码/src/main.ts`
- 用户端路由：`/`
- 运营端路由：`/ops`

## 2. UI 文件职责

| 文件 | 职责 |
| --- | --- |
| `src/pages/MobileApp.vue` | 用户端首页、对话流、历史会话、输入框与问题衍生 |
| `src/components/ReportResultsGroup.vue` | 推荐结果分组、前三条与剩余结果折叠 |
| `src/components/RecommendationCard.vue` | 单个报告卡片、详情/标签展开、关联案例动作 |
| `src/pages/OpsApp.vue` | 运营概览、对话历史、模型配置后台 |
| `src/styles.css` | 全局布局、首页卡片、聊天气泡、抽屉和运营后台 |
| `src/unified.css` | 结果卡片细化、引导卡片、问题衍生气泡 |
| `src/api.ts` | API 基址与 JSON 请求封装 |

## 3. 视觉基础

- 主色：`#1760b2` / `#1769e0`
- 深蓝渐变：`#1c63bc` → `#0e407f`
- 页面底色：`#f3f6fb` / `#f4f7fb`
- 卡片底色：`#ffffff`
- 分割线：`#dce7f3`、`#edf2f7`
- 正文：`#16243a`
- 次级文字：`#718197`
- 圆角：普通气泡 17px，结果卡片 16–18px，问题衍生胶囊 16px
- 字体：`Inter, "Microsoft YaHei", system-ui, sans-serif`

## 4. 卡片样式

### 推荐结果卡片

根节点类名为 `.recommend-card`。结构依次为：

1. `.recommend-head`：报告类型、标题、匹配分。
2. `.reason`：推荐理由。
3. `.recommend-actions`：查看详情、查看标签、关联案例。
4. `.report-tag-list`：展开后的标签列表。
5. `.summary-grid`：展开后的报告摘要。

默认卡片使用白底、16px 圆角、浅边框和弱投影；剩余结果使用 `.compact` 降低内边距并移除投影。标签项使用 `#f7faff` 浅蓝底、12px 圆角。

### 首页功能卡片

- `.hero-card`：左侧主推荐入口，蓝色渐变大卡片。
- `.guess-card`：右上方默认问题列表，不显示“换一批”。
- `.discovery-side .feature-strip`：右下方三个次要功能入口。
- `.guide-card`：功能输入示例，引导用户继续对话。

## 5. 聊天气泡与追问气泡

### 对话气泡

- 用户消息：`.message.user .bubble`，主色背景、白字、右下角 5px。
- 助手消息：`.message.assistant .bubble`，白底、左上角 5px。
- 意图标签：`.intent-label`，浅蓝底小标签。

### 问题衍生气泡

问题衍生区域使用 `.message-suggestions`：

- 标题独占一行，12px 次级文字。
- 每条追问为白底、蓝灰边框、16px 圆角的可点击胶囊。
- 图标与文字间距 5px，图标使用主蓝色。
- 容器允许换行，适配窄屏。

独立可复用规则见 `卡片与追问气泡.css`。

## 6. 响应式规则

- 用户端应用壳最大宽度 520px，桌面端居中展示。
- 首页发现区保持左右两栏；右侧三个次要功能使用等宽三列。
- 380px 以下：页面内边距收紧，结果和追问区域左边距缩小。
- 运营后台 1000px 以下：侧栏与内容区缩窄，指标卡改为两列，筛选栏改为两列。

## 7. API 对接

默认 API 前缀为 `/api/v1`，可通过 `VITE_API_BASE_URL` 覆盖。用户端依赖：

- `GET /ui/bootstrap`
- `POST /suggestions`
- `POST /chat`
- `GET /users/{user_id}/conversations`
- `GET /conversations/{session_id}`

运营端依赖 `/ops/metrics`、`/ops/model-status`、`/ops/conversations`、`/ops/model-profiles` 等接口。

## 8. 部署注意事项

- `VITE_BASE_PATH` 必须与实际子路径完全一致，并以 `/` 结尾。
- 当前 Xanadu 的生产变量为 `VITE_BASE_PATH=/due-diligence/`、`VITE_API_BASE_URL=/due-diligence/api/v1`。
- 网关需对前端路由做 history fallback 到 `index.html`。
- 用户端会将匿名演示用户 ID 写入 `localStorage`，键名为 `dda_user_id`。
- 前端不再提供历史对话入口；顶部仅保留位于右侧的新建会话按钮。
- 运营端不在前端内处理登录，必须由可信网关保护页面及 `/api/v1/ops/*`。
- 不要提交真实 API Key；模型配置中的密钥只应通过受保护的运营接口传输。
