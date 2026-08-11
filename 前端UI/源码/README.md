# 立功竞赛助手 UI 源码说明

本目录只保留与 UI 展示和页面交互直接相关的源码，供正式前端团队复制、拆分或重新实现。

它不是完整的可独立安装工程，因此不包含：

- `package.json`、`package-lock.json`
- Vite、TypeScript 构建配置
- 环境变量文件
- 单元测试
- 构建产物
- 后端代码和部署脚本

线上效果参考：<https://pianwei.shadlc.net/due-diligence/>

## 目录结构

```text
源码/
├─ README.md
└─ src/
   ├─ main.ts
   ├─ api.ts
   ├─ styles.css
   ├─ unified.css
   ├─ pages/
   │  ├─ MobileApp.vue
   │  └─ OpsApp.vue
   └─ components/
      ├─ RecommendationCard.vue
      └─ ReportResultsGroup.vue
```

## 文件用途

### `src/pages/MobileApp.vue`

用户端主页面，包含：

- “立功竞赛助手”顶部栏。
- 右侧新建会话按钮。
- 欢迎气泡。
- 左侧智能案例推荐大卡片。
- 右上“猜你想问”。
- 右下多维筛选、数据统计、比赛问答。
- 用户与助手消息气泡。
- 推荐报告结果。
- 问题衍生追问气泡。
- 底部输入框。

这是正式前端接入时最主要的参考文件。

### `src/components/RecommendationCard.vue`

单份推荐报告卡片，包含：

- 报告类型和标题。
- 匹配分。
- 推荐理由。
- 查看详情。
- 查看标签。
- 关联案例按钮。
- 标签和报告摘要展开状态。

主要数据结构：

```ts
interface RecommendationItem {
  report_id: string
  report_name: string
  report_type: string
  score?: number
  recommendation_reason?: string
  report_tags?: Array<{
    name: string
    value: string
  }>
  summary?: Record<string, string | string[]>
}
```

### `src/components/ReportResultsGroup.vue`

推荐结果列表容器：

- 默认展示前三份报告。
- 其余报告折叠展示。
- 调用 `RecommendationCard.vue`。
- 将关联案例事件传递给父页面。

Vue 使用示例：

```vue
<ReportResultsGroup
  :items="recommendations"
  :allow-related="true"
  @related="handleRelated"
/>
```

### `src/pages/OpsApp.vue`

运营后台 UI，包含：

- 运营指标卡片。
- 功能使用情况。
- 对话历史表格和详情抽屉。
- 模型配置卡片和编辑弹窗。

如果正式前端只实现用户端，可以不使用此文件。

### `src/styles.css`

基础视觉样式，包含：

- 页面整体布局。
- 顶部栏和底部输入框。
- 首页功能卡片。
- 用户与助手聊天气泡。
- 推荐卡片基础样式。
- 运营后台样式。

### `src/unified.css`

新版 UI 的覆盖和细化样式，包含：

- 首页左右两栏布局。
- 右侧三个功能入口。
- 推荐结果卡片。
- 标签展开样式。
- 问题衍生追问气泡。
- 380px、430px 窄屏适配。

两份样式应按照以下顺序加载：

```ts
import './styles.css'
import './unified.css'
```

### `src/main.ts`

展示原页面的入口和路由关系：

```text
/      → MobileApp.vue
/ops   → OpsApp.vue
```

正式前端可以直接使用自己的路由系统，不要求复制此文件。

### `src/api.ts`

页面使用的轻量 Fetch 请求封装。保留该文件是为了说明页面如何调用接口。

正式前端如果已有 Axios、Fetch SDK 或统一请求层，可以不用此文件，只需把页面中的 `api`、`post` 调用替换为现有请求方法。

## 正式前端建议怎么用

### Vue 3 项目

建议复制：

```text
src/pages/MobileApp.vue
src/components/RecommendationCard.vue
src/components/ReportResultsGroup.vue
src/styles.css
src/unified.css
```

然后：

1. 注册 `MobileApp.vue` 路由。
2. 保持两份 CSS 的加载顺序。
3. 将 `api.ts` 替换或接入正式项目的请求层。
4. 把 `localStorage` 中的匿名用户 ID 替换为正式登录用户 ID。
5. 按现有设计系统调整颜色、字体、间距和圆角。
6. 使用上级目录中的 UI 截图进行视觉验收。

### React、小程序或其他技术栈

不需要复用 Vue 文件的脚本部分，可以：

1. 按照 `MobileApp.vue` 的模板结构重建页面。
2. 按照两个卡片组件重建推荐结果。
3. 提取 `styles.css` 和 `unified.css` 中对应 class 的视觉规则。
4. 参考上级目录截图验证布局和状态。

## 用户端接口

页面主要使用三个接口：

```text
GET  /ui/bootstrap
POST /suggestions
POST /chat
```

### 初始化页面

```http
GET /ui/bootstrap?user_id={user_id}
```

用于获取欢迎语、默认问题和功能卡片。

### 获取问题建议

```json
{
  "user_id": "user-001",
  "session_id": "session-001"
}
```

### 发送聊天消息

```json
{
  "user_id": "user-001",
  "session_id": "session-001",
  "message": "推荐几个优秀的尽调报告"
}
```

### 查询关联案例

```json
{
  "user_id": "user-001",
  "session_id": "session-001",
  "action": {
    "type": "related_reports",
    "report_id": "report-001"
  }
}
```

页面主要读取响应中的：

```text
session_id
assistant_message
intent
status
recommendations
answer
```

## 样式参考

除本目录中的两份 CSS 外，上级目录还提供：

```text
../UI截图/
../样式规范/UI样式说明.md
../样式规范/卡片与追问气泡.css
```

其中 `卡片与追问气泡.css` 可以独立交给前端，用于快速定位推荐卡片、对话气泡和问题衍生气泡的核心视觉规则。

## 注意事项

- `MobileApp.vue` 当前使用 `localStorage` 保存匿名用户 ID，键名为 `dda_user_id`。
- 页面已删除用户端历史对话入口，只保留新建会话。
- `OpsApp.vue` 不包含登录认证，运营页面必须由正式网关或统一身份认证保护。
- CSS 中的颜色和尺寸是当前线上参考值，正式前端可以转换为自己的 Design Token。
