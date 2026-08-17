<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, downloadFile, post, request } from '../api'
import OpsIcon from '../components/OpsIcon.vue'

type OpsPage = 'overview' | 'history' | 'models'
type ToastTone = 'success' | 'error' | 'info'

const page = ref<OpsPage>('overview')
const metrics = ref<any>(null)
const modelStatus = ref<any>(null)
const conversations = ref<any[]>([])
const profiles = ref<any[]>([])
const selected = ref<any>(null)
const detail = ref<any>(null)
const modalOpen = ref(false)
const mobileNavOpen = ref(false)
const masterKeyConfigured = ref(false)
const filters = ref({ user_id: '', keyword: '', feature: '' })
const timeRange = ref<'' | '1' | '3' | '7' | '30'>('7')
const timeOptions = [
  { value: '1', label: '过去 1 天' },
  { value: '3', label: '过去 3 天' },
  { value: '7', label: '过去 7 天' },
  { value: '30', label: '过去 30 天' },
  { value: '', label: '全部' },
] as const
const form = ref<any>(emptyForm())
const overviewLoading = ref(false)
const historyLoading = ref(false)
const profilesLoading = ref(false)
const detailLoading = ref(false)
const saving = ref(false)
const actionBusy = ref('')
const exporting = ref(false)
const updatedAt = ref<Date | null>(null)
const nextCursor = ref<string | null>(null)
const historyCursor = ref<string | null>(null)
const historyStack = ref<Array<string | null>>([])
const toast = ref<{ text: string, tone: ToastTone } | null>(null)
const confirmation = ref<{ kind: 'activate' | 'delete', profile: any } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | undefined

const title = computed(() => ({ overview: '运营概览', history: '对话历史', models: '模型配置' }[page.value]))
const subtitle = computed(() => ({ overview: '掌握服务规模、能力使用与模型运行状态', history: '检索、筛选并复盘用户与助手的完整对话', models: '测试并安全切换 OpenAI 兼容模型配置' }[page.value]))
const timeRangeLabel = computed(() => timeOptions.find(option => option.value === timeRange.value)?.label || '全部')
const intentNames: Record<string, string> = { recommendation: '案例推荐', filter: '多维筛选', statistics: '数据统计', qa: '比赛问答', greeting: '问候', mixed: '混合会话', unsupported: '越界拒绝', unknown: '未识别' }
const intentName = (value: string) => intentNames[value] || value || '未识别'
const featureEntries = computed(() => {
  const entries = Object.entries(metrics.value?.feature_usage || {}).map(([name, count]) => ({ name, count: Number(count) }))
  const maximum = Math.max(1, ...entries.map(item => item.count))
  const total = Math.max(1, entries.reduce((sum, item) => sum + item.count, 0))
  return entries.sort((a, b) => b.count - a.count).map(item => ({ ...item, width: Math.max(6, Math.round(item.count / maximum * 100)), share: Math.round(item.count / total * 100) }))
})

function emptyForm() {
  return { name: '', provider: 'OpenAI Compatible', base_url: 'https://api.deepseek.com', model: 'deepseek-chat', api_key: '', clear_api_key: false, timeout_seconds: 30, json_mode: true, disable_thinking: false }
}

const formatNumber = (value: unknown) => new Intl.NumberFormat('zh-CN').format(Number(value || 0))
const formatDate = (value: string | null | undefined) => value ? String(value).replace('T', ' ').slice(0, 19) : '—'
const timeLabel = (value: Date | null) => value ? value.toLocaleTimeString('zh-CN', { hour12: false }) : '尚未同步'
const normalizeConversation = (item: any) => ({ ...item, feature_label: intentName(item.feature) })

function showToast(text: string, tone: ToastTone = 'info') {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { text, tone }
  toastTimer = setTimeout(() => { toast.value = null }, 3600)
}

async function loadOverview(silent = false) {
  if (!silent) overviewLoading.value = true
  try {
    const [metricData, statusData] = await Promise.all([api<any>('/ops/metrics'), api<any>('/ops/model-status')])
    metricData.recent_conversations = (metricData.recent_conversations || []).map(normalizeConversation)
    metricData.feature_usage = Object.fromEntries(Object.entries(metricData.feature_usage || {}).map(([key, value]) => [intentName(key), value]))
    metrics.value = metricData
    modelStatus.value = statusData
    updatedAt.value = new Date()
    if (silent) showToast('运营数据已刷新', 'success')
  } catch (error: any) {
    showToast(error.message || '运营数据加载失败', 'error')
  } finally {
    overviewLoading.value = false
  }
}

async function loadHistory(reset = false) {
  if (reset) { historyCursor.value = null; historyStack.value = [] }
  historyLoading.value = true
  try {
    const params = historyQueryParams()
    params.set('limit', '15')
    if (historyCursor.value) params.set('cursor', historyCursor.value)
    const result: any = await api('/ops/conversations?' + params)
    conversations.value = (result.items || []).map(normalizeConversation)
    nextCursor.value = result.next_cursor || null
  } catch (error: any) {
    showToast(error.message || '会话加载失败', 'error')
  } finally {
    historyLoading.value = false
  }
}

function historyQueryParams() {
  const params = new URLSearchParams()
  if (filters.value.user_id.trim()) params.set('user_id', filters.value.user_id.trim())
  if (filters.value.keyword.trim()) params.set('keyword', filters.value.keyword.trim())
  if (filters.value.feature) params.set('feature', filters.value.feature)
  if (timeRange.value) params.set('days', timeRange.value)
  return params
}

async function selectTimeRange(value: '' | '1' | '3' | '7' | '30') {
  timeRange.value = value
  await loadHistory(true)
}

async function exportHistory() {
  exporting.value = true
  try {
    const params = historyQueryParams()
    await downloadFile(`/ops/conversations/export?${params}`, 'conversation-logs.csv')
    showToast(`已导出${timeRangeLabel.value}的筛选日志`, 'success')
  } catch (error: any) {
    showToast(error.message || '日志导出失败', 'error')
  } finally {
    exporting.value = false
  }
}

async function loadProfiles() {
  profilesLoading.value = true
  try {
    const result: any = await api('/ops/model-profiles')
    profiles.value = result.items || []
    masterKeyConfigured.value = Boolean(result.master_key_configured)
  } catch (error: any) {
    showToast(error.message || '模型配置加载失败', 'error')
  } finally {
    profilesLoading.value = false
  }
}

async function navigate(to: OpsPage) {
  page.value = to
  detail.value = null
  mobileNavOpen.value = false
  if (to === 'overview') await loadOverview()
  if (to === 'history') await loadHistory(true)
  if (to === 'models') await loadProfiles()
}

async function showConversation(id: string) {
  detailLoading.value = true
  detail.value = { session_id: id, title: '正在加载会话…', messages: [], tags: [] }
  try {
    const result: any = await api('/ops/conversations/' + encodeURIComponent(id))
    result.feature_label = intentName(result.feature)
    result.messages = (result.messages || []).map((message: any) => ({ ...message, intent_label: message.intent ? intentName(message.intent) : '' }))
    detail.value = result
  } catch (error: any) {
    detail.value = null
    showToast(error.message || '会话详情加载失败', 'error')
  } finally {
    detailLoading.value = false
  }
}

function resetFilters() { filters.value = { user_id: '', keyword: '', feature: '' }; timeRange.value = '7'; loadHistory(true) }
function nextHistoryPage() { if (nextCursor.value) { historyStack.value.push(historyCursor.value); historyCursor.value = nextCursor.value; loadHistory() } }
function previousHistoryPage() { if (historyStack.value.length) { historyCursor.value = historyStack.value.pop() ?? null; loadHistory() } }

function editProfile(profile?: any) {
  selected.value = profile || null
  form.value = profile ? { name: profile.name, provider: profile.provider, base_url: profile.base_url, model: profile.model, api_key: '', clear_api_key: false, timeout_seconds: profile.timeout_seconds, json_mode: profile.json_mode, disable_thinking: profile.disable_thinking } : emptyForm()
  modalOpen.value = true
}

function closeProfile() { if (!saving.value) { modalOpen.value = false; selected.value = null } }

async function saveProfile() {
  saving.value = true
  try {
    if (selected.value) await request('/ops/model-profiles/' + selected.value.profile_id, { method: 'PATCH', body: JSON.stringify(form.value) })
    else await post('/ops/model-profiles', form.value)
    modalOpen.value = false
    selected.value = null
    await loadProfiles()
    showToast('模型配置已保存', 'success')
  } catch (error: any) {
    showToast(error.message || '配置保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function testProfile(profile: any) {
  actionBusy.value = `test:${profile.profile_id}`
  try {
    const result: any = await post(`/ops/model-profiles/${profile.profile_id}/test`, {})
    showToast(result.success ? `测试成功，延迟 ${Math.round(result.latency_ms)}ms` : `测试失败：${result.error_type || '连接异常'}`, result.success ? 'success' : 'error')
    await loadProfiles()
  } catch (error: any) {
    showToast(error.message || '模型测试失败', 'error')
  } finally {
    actionBusy.value = ''
  }
}

function askConfirmation(kind: 'activate' | 'delete', profile: any) { confirmation.value = { kind, profile } }

async function performConfirmation() {
  if (!confirmation.value) return
  const { kind, profile } = confirmation.value
  confirmation.value = null
  actionBusy.value = `${kind}:${profile.profile_id}`
  try {
    if (kind === 'activate') {
      await post(`/ops/model-profiles/${profile.profile_id}/activate`, {})
      showToast(`已激活“${profile.name}”`, 'success')
      await Promise.all([loadProfiles(), loadOverview()])
    } else {
      await request(`/ops/model-profiles/${profile.profile_id}`, { method: 'DELETE' })
      showToast(`已删除“${profile.name}”`, 'success')
      await loadProfiles()
    }
  } catch (error: any) {
    showToast(error.message || '操作失败', 'error')
  } finally {
    actionBusy.value = ''
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  if (confirmation.value) confirmation.value = null
  else if (modalOpen.value) closeProfile()
  else if (detail.value) detail.value = null
  else mobileNavOpen.value = false
}

onMounted(() => { document.title = '立功竞赛运营管理平台'; window.addEventListener('keydown', onKeydown); loadOverview() })
onBeforeUnmount(() => { document.title = '立功竞赛助手'; window.removeEventListener('keydown', onKeydown); if (toastTimer) clearTimeout(toastTimer) })
</script>

<template>
  <div class="ops-shell">
    <button v-if="mobileNavOpen" class="ops-nav-overlay" aria-label="关闭导航" @click="mobileNavOpen=false"></button>
    <aside :class="['ops-sidebar', { open: mobileNavOpen }]">
      <div class="ops-brand"><span>立</span><div><b>立功竞赛</b><small>运营管理平台</small></div></div>
      <nav aria-label="运营端主导航">
        <button :class="{active:page==='overview'}" @click="navigate('overview')"><OpsIcon name="dashboard"/><span>运营概览</span></button>
        <button :class="{active:page==='history'}" @click="navigate('history')"><OpsIcon name="message"/><span>对话历史</span></button>
        <button :class="{active:page==='models'}" @click="navigate('models')"><OpsIcon name="cpu"/><span>模型配置</span></button>
      </nav>
      <div class="ops-side-note"><OpsIcon name="shield" :size="15"/><span>仅限可信内网使用</span></div>
      <div class="ops-version">内部服务 · v1.0</div>
    </aside>

    <main class="ops-main">
      <header class="ops-header">
        <button class="ops-menu-button" aria-label="打开导航" @click="mobileNavOpen=true"><OpsIcon name="menu"/></button>
        <div class="ops-title"><h1>{{ title }}</h1><p>{{ subtitle }}</p></div>
        <div class="ops-header-actions">
          <div class="ops-sync-time"><span>最近同步</span><b>{{ timeLabel(updatedAt) }}</b></div>
          <span :class="['status-dot', { warning: modelStatus && !modelStatus.healthy }]">● {{ modelStatus && !modelStatus.healthy ? '模型未就绪' : '服务运行中' }}</span>
          <button v-if="page==='overview'" class="icon-button" :disabled="overviewLoading" aria-label="刷新运营数据" @click="loadOverview(true)"><OpsIcon name="refresh" :class="{spinning:overviewLoading}"/></button>
        </div>
      </header>

      <div class="risk-banner"><OpsIcon name="alert" :size="17"/><span><b>安全提示：</b>应用自身不处理登录；公网部署必须由 Nginx 等可信网关保护运营页面和运营接口。</span></div>

      <section v-if="page==='overview'" class="ops-content" aria-live="polite">
        <div v-if="overviewLoading && !metrics" class="ops-loading-card">正在加载运营数据…</div>
        <template v-else-if="metrics">
          <div class="metric-grid">
            <article><span class="metric-icon"><OpsIcon name="users"/></span><small>用户数</small><b>{{ formatNumber(metrics.users) }}</b><em>累计访问用户</em></article>
            <article><span class="metric-icon"><OpsIcon name="sessions"/></span><small>服务会话</small><b>{{ formatNumber(metrics.sessions) }}</b><em>全部功能会话</em></article>
            <article><span class="metric-icon"><OpsIcon name="send"/></span><small>交互消息</small><b>{{ formatNumber(metrics.messages) }}</b><em>用户与助手消息</em></article>
            <article :class="{ danger: metrics.model_failures > 0 }"><span class="metric-icon"><OpsIcon name="alert"/></span><small>模型调用失败</small><b>{{ formatNumber(metrics.model_failures) }}</b><em>{{ metrics.model_failures ? '建议立即排查' : '当前无异常记录' }}</em></article>
          </div>

          <div class="ops-columns">
            <section class="ops-card usage-card">
              <div class="card-heading"><div><h2>功能使用情况</h2><p>按用户消息意图统计，进度条相对最高使用量</p></div><span class="subtle-badge">共 {{ formatNumber(featureEntries.reduce((sum,item)=>sum+item.count,0)) }} 次</span></div>
              <div v-if="featureEntries.length" class="usage-list"><div v-for="item in featureEntries" :key="item.name" class="usage-row"><span>{{ item.name }}</span><i><u :style="{width:item.width+'%'}"></u></i><b>{{ formatNumber(item.count) }}</b><small>{{ item.share }}%</small></div></div>
              <div v-else class="compact-empty">暂无功能使用数据</div>
            </section>

            <section class="ops-card model-health">
              <div class="card-heading"><div><h2>当前激活模型</h2><p>实时使用中的模型连接</p></div><span :class="['health-pill',modelStatus?.healthy?'ok':'warn']">{{ modelStatus?.healthy?'运行正常':'未就绪' }}</span></div>
              <div class="model-summary"><span class="model-logo">AI</span><div><b>{{ modelStatus?.profile_name || '环境变量配置' }}</b><p>{{ modelStatus?.model || '未配置模型' }}</p></div></div>
              <dl><div><dt>配置来源</dt><dd>{{ modelStatus?.source==='database'?'数据库配置':'环境变量' }}</dd></div><div><dt>模型状态</dt><dd>{{ modelStatus?.configured?'已配置':'配置不完整' }}</dd></div></dl>
              <button class="secondary-button full" @click="navigate('models')">进入模型配置 <OpsIcon name="arrow" :size="15"/></button>
            </section>
          </div>

          <section class="ops-card recent-card">
            <div class="card-heading"><div><h2>最近会话</h2><p>最近更新的 5 个用户会话</p></div><button class="text-button" @click="navigate('history')">查看全部 <OpsIcon name="arrow" :size="15"/></button></div>
            <div class="ops-table-wrap"><table><thead><tr><th>会话标题</th><th>用户</th><th>功能</th><th>消息数</th><th>更新时间</th><th><span class="sr-only">操作</span></th></tr></thead><tbody><tr v-for="item in metrics.recent_conversations" :key="item.session_id" tabindex="0" @click="showConversation(item.session_id)" @keyup.enter="showConversation(item.session_id)"><td><b>{{ item.title }}</b></td><td class="mono">{{ item.user_id }}</td><td><span class="feature-badge">{{ item.feature_label }}</span></td><td>{{ item.message_count }}</td><td>{{ formatDate(item.updated_at) }}</td><td><button class="row-action" @click.stop="showConversation(item.session_id)">详情</button></td></tr></tbody></table><div v-if="!metrics.recent_conversations.length" class="empty-state">暂无会话记录</div></div>
          </section>
        </template>
      </section>

      <section v-if="page==='history'" class="ops-content">
        <form class="filter-bar" @submit.prevent="loadHistory(true)">
          <div class="time-filter-row" role="group" aria-label="按会话开始时间筛选">
            <span class="time-filter-label"><OpsIcon name="clock" :size="15"/>时间范围</span>
            <div class="time-filter-options">
              <button v-for="option in timeOptions" :key="option.label" type="button" :class="['time-filter-option',{active:timeRange===option.value}]" :aria-pressed="timeRange===option.value" :disabled="historyLoading" @click="selectTimeRange(option.value)">{{ option.label }}</button>
            </div>
          </div>
          <label><span>用户 ID</span><input v-model="filters.user_id" placeholder="输入完整用户 ID"/></label>
          <label class="keyword-field"><span>会话关键词</span><div><OpsIcon name="search" :size="16"/><input v-model="filters.keyword" placeholder="搜索用户消息内容"/></div></label>
          <label><span>功能类型</span><select v-model="filters.feature"><option value="">全部功能</option><option value="recommendation">案例推荐</option><option value="filter">多维筛选</option><option value="statistics">数据统计</option><option value="qa">比赛问答</option><option value="mixed">混合会话</option></select></label>
          <div class="filter-actions"><button type="button" class="secondary-button export-button" :disabled="exporting||historyLoading" @click="exportHistory"><OpsIcon name="download" :size="15"/>{{ exporting?'导出中':'导出当前结果' }}</button><button type="button" class="secondary-button" @click="resetFilters"><OpsIcon name="reset" :size="15"/>重置</button><button class="ops-primary" :disabled="historyLoading"><OpsIcon name="search" :size="15"/>{{ historyLoading?'查询中':'查询' }}</button></div>
        </form>
        <section class="ops-card history-card">
          <div class="card-heading"><div><h2>会话记录</h2><p>当前页 {{ conversations.length }} 条，每页最多 15 条</p></div><div class="history-heading-actions"><span class="subtle-badge"><OpsIcon name="clock" :size="12"/>{{ timeRangeLabel }}</span><span v-if="filters.user_id||filters.keyword||filters.feature" class="subtle-badge">已应用其他筛选</span></div></div>
          <div class="ops-table-wrap"><table><thead><tr><th>会话标题</th><th>用户 ID</th><th>功能</th><th>消息数</th><th>开始时间</th><th>更新时间</th><th>操作</th></tr></thead><tbody><tr v-for="item in conversations" :key="item.session_id"><td><b>{{ item.title }}</b><small class="session-id">{{ item.session_id }}</small></td><td class="mono">{{ item.user_id }}</td><td><span class="feature-badge">{{ item.feature_label }}</span></td><td>{{ item.message_count }}</td><td>{{ formatDate(item.created_at) }}</td><td>{{ formatDate(item.updated_at) }}</td><td><button class="row-action" @click="showConversation(item.session_id)">查看详情</button></td></tr></tbody></table><div v-if="historyLoading" class="table-loading">正在加载会话…</div><div v-else-if="!conversations.length" class="empty-state"><OpsIcon name="message" :size="28"/><b>暂无符合条件的会话</b><span>调整筛选条件后重试</span></div></div>
          <footer class="pagination"><span>第 {{ historyStack.length + 1 }} 页</span><div><button class="secondary-button" :disabled="!historyStack.length||historyLoading" @click="previousHistoryPage">上一页</button><button class="secondary-button" :disabled="!nextCursor||historyLoading" @click="nextHistoryPage">下一页</button></div></footer>
        </section>
      </section>

      <section v-if="page==='models'" class="ops-content">
        <div class="page-action"><div><h2>模型配置</h2><p>配置需先完成连通性测试，成功后方可激活。</p></div><button class="ops-primary" @click="editProfile()"><OpsIcon name="plus" :size="16"/>新建配置</button></div>
        <div v-if="!masterKeyConfigured" class="master-key-warning"><OpsIcon name="key" :size="18"/><div><b>尚未配置模型密钥主密钥</b><span>未设置 MODEL_CONFIG_MASTER_KEY 时，包含 API Key 的配置无法安全保存。</span></div></div>
        <div v-if="profilesLoading" class="ops-loading-card">正在加载模型配置…</div>
        <div v-else class="profile-grid">
          <article v-for="profile in profiles" :key="profile.profile_id" :class="['profile-card',{active:profile.is_active}]">
            <div class="profile-top"><span class="model-logo small">AI</span><div><h3>{{ profile.name }}</h3><p>{{ profile.provider }}</p></div><span v-if="profile.is_active" class="active-badge">当前激活</span></div>
            <dl><div><dt>模型名称</dt><dd>{{ profile.model }}</dd></div><div><dt>服务地址</dt><dd :title="profile.base_url">{{ profile.base_url }}</dd></div><div><dt>API Key</dt><dd>{{ profile.api_key_masked || '未设置' }}</dd></div><div><dt>请求超时</dt><dd>{{ profile.timeout_seconds }} 秒</dd></div></dl>
            <div class="profile-test"><div><span>最近测试</span><b :class="['test-status',profile.last_test_status]">{{ profile.last_test_status==='success'?'测试通过':profile.last_test_status==='failed'?'测试失败':'尚未测试' }}</b></div><span v-if="profile.last_test_latency_ms">{{ Math.round(profile.last_test_latency_ms) }}ms</span><span v-else>—</span></div>
            <div class="profile-actions">
              <button v-if="!profile.is_active" :disabled="Boolean(actionBusy)" @click="editProfile(profile)"><OpsIcon name="edit" :size="15"/>编辑</button>
              <button :disabled="Boolean(actionBusy)" @click="testProfile(profile)"><OpsIcon name="test" :size="15"/>{{ actionBusy===`test:${profile.profile_id}`?'测试中':'测试' }}</button>
              <button v-if="!profile.is_active" class="activate" :disabled="Boolean(actionBusy)||profile.last_test_status!=='success'" :title="profile.last_test_status==='success'?'激活此配置':'请先测试成功'" @click="askConfirmation('activate',profile)"><OpsIcon name="check" :size="15"/>激活</button>
              <button v-if="!profile.is_active" class="delete" :disabled="Boolean(actionBusy)" @click="askConfirmation('delete',profile)"><OpsIcon name="trash" :size="15"/>删除</button>
              <span v-else class="active-help">活动配置不可直接编辑或删除</span>
            </div>
          </article>
          <div v-if="!profiles.length" class="empty-profile"><OpsIcon name="cpu" :size="30"/><b>尚未创建数据库模型配置</b><span>服务当前使用环境变量配置，可新建配置并在测试后切换。</span><button class="ops-primary" @click="editProfile()"><OpsIcon name="plus" :size="15"/>新建配置</button></div>
        </div>
      </section>
    </main>

    <div v-if="detail" class="ops-drawer-mask" @click.self="detail=null"><aside class="ops-drawer" role="dialog" aria-modal="true" aria-labelledby="conversation-title"><div class="drawer-title"><div><span class="drawer-kicker">会话详情</span><h2 id="conversation-title">{{ detail.title }}</h2><p>{{ detail.user_id || '—' }} · {{ detail.feature_label || '加载中' }} · {{ formatDate(detail.updated_at) }}</p></div><button aria-label="关闭会话详情" @click="detail=null"><OpsIcon name="close"/></button></div><div v-if="detailLoading" class="drawer-loading">正在加载完整对话…</div><template v-else><div v-if="detail.tags?.length" class="tag-cloud"><span v-for="tag in detail.tags" :key="tag.name"><b>{{ tag.name }}</b>{{ tag.value }}</span></div><div class="timeline"><article v-for="message in detail.messages" :key="message.id" :class="message.role"><header><span>{{ message.role==='user'?'用户':'助手' }}</span><em v-if="message.intent_label">{{ message.intent_label }}</em><time>{{ formatDate(message.created_at) }}</time></header><p>{{ message.content }}</p><div v-if="message.payload?.recommendations" class="payload-summary">包含 {{ message.payload.recommendations.length }} 条报告结果</div></article><div v-if="!detail.messages?.length" class="empty-state">暂无消息内容</div></div></template></aside></div>

    <div v-if="modalOpen" class="modal-mask" @click.self="closeProfile"><form class="profile-modal" role="dialog" aria-modal="true" aria-labelledby="profile-title" @submit.prevent="saveProfile"><div class="drawer-title"><div><span class="drawer-kicker">模型中心</span><h2 id="profile-title">{{ selected?'编辑模型配置':'新建模型配置' }}</h2><p>{{ selected?'留空 API Key 将保留原密钥':'创建后请先测试连接，再执行激活' }}</p></div><button type="button" aria-label="关闭配置表单" @click="closeProfile"><OpsIcon name="close"/></button></div><div class="profile-form-grid"><label><span>配置名称</span><input v-model.trim="form.name" required maxlength="80" placeholder="例如：行内主模型"/></label><label><span>提供方</span><input v-model.trim="form.provider" required maxlength="80"/></label><label class="full-field"><span>Base URL</span><input v-model.trim="form.base_url" required type="url" placeholder="https://example.com/v1"/></label><label><span>模型名称</span><input v-model.trim="form.model" required placeholder="模型标识"/></label><label><span>请求超时（秒）</span><input v-model.number="form.timeout_seconds" required type="number" min="1" max="600"/></label><label class="full-field"><span>API Key</span><input v-model="form.api_key" type="password" autocomplete="new-password" :placeholder="selected?'留空则保留原密钥':'可按行内鉴权要求填写'"/></label></div><label v-if="selected" class="clear-key"><input v-model="form.clear_api_key" type="checkbox"/>清除已保存的 API Key</label><div class="checks"><label><input v-model="form.json_mode" type="checkbox"/>启用 JSON Output</label><label><input v-model="form.disable_thinking" type="checkbox"/>关闭思考模式</label></div><footer class="modal-actions"><button type="button" class="secondary-button" @click="closeProfile">取消</button><button class="ops-primary" :disabled="saving">{{ saving?'保存中…':'保存配置' }}</button></footer></form></div>

    <div v-if="confirmation" class="modal-mask" @click.self="confirmation=null"><section class="confirm-modal" role="alertdialog" aria-modal="true"><span :class="['confirm-icon',confirmation.kind]"><OpsIcon :name="confirmation.kind==='delete'?'trash':'check'" :size="22"/></span><h2>{{ confirmation.kind==='delete'?'删除模型配置':'激活模型配置' }}</h2><p v-if="confirmation.kind==='delete'">删除“{{ confirmation.profile.name }}”后无法恢复。活动配置不会被删除。</p><p v-else>确认将“{{ confirmation.profile.name }}”设为当前活动模型？新请求将立即使用该配置。</p><div><button class="secondary-button" @click="confirmation=null">取消</button><button :class="confirmation.kind==='delete'?'danger-button':'ops-primary'" @click="performConfirmation">确认{{ confirmation.kind==='delete'?'删除':'激活' }}</button></div></section></div>

    <Transition name="toast"><div v-if="toast" :class="['ops-toast',toast.tone]" role="status"><OpsIcon :name="toast.tone==='success'?'check':toast.tone==='error'?'alert':'message'" :size="17"/><span>{{ toast.text }}</span><button aria-label="关闭提示" @click="toast=null"><OpsIcon name="close" :size="15"/></button></div></Transition>
  </div>
</template>
