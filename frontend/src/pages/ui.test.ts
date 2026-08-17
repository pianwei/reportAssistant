// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MobileApp from './MobileApp.vue'
import OpsApp from './OpsApp.vue'
import RecommendationCard from '../components/RecommendationCard.vue'
import ReportResultsGroup from '../components/ReportResultsGroup.vue'

const response = (body: unknown, status = 200, headers: Record<string, string> = {}) => Promise.resolve({
  ok: status >= 200 && status < 300,
  status,
  json: () => Promise.resolve(body),
  headers: new Headers(headers),
  blob: () => Promise.resolve(new Blob([typeof body === 'string' ? body : JSON.stringify(body)])),
}) as Promise<Response>

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('crypto', { randomUUID: () => '12345678-1234-1234-1234-123456789abc' })
})
afterEach(() => vi.restoreAllMocks())

describe('移动助手', () => {
  it('初始化首页并点击建议后发送用户和会话数据', async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url.includes('/ui/bootstrap')) return response({
        assistant: { intro: '您好，我是尽调助手' },
        default_suggestions: [{ text: '如何推荐报告？', intent: 'recommendation' }],
        feature_cards: [{ id: 'recommendation', icon: 'spark', title: '智能推荐', description: '推荐案例', input_examples: ['推荐报告'], assistant_example: '请介绍关注方面' }],
      })
      if (url.includes('/suggestions')) return response({ suggestions: [{ text: '科技企业怎么选？', intent: 'recommendation' }], source: 'fallback', batch_id: 'batch-1' })
      if (url.includes('/chat')) return response({
        session_id: 'ses-1', intent: 'recommendation', status: 'needs_clarification', assistant_message: '请问客户所属行业？',
        question: { tag_name: '行业分类', examples: ['制造业'], skippable: true, allow_finish: true }, recommendations: [],
      })
      throw new Error(`unexpected request ${url} ${options?.method}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(MobileApp)
    await flushPromises()
    expect(wrapper.text()).toContain('您好，我是立功竞赛助手')
    expect(wrapper.find('[aria-label="历史记录"]').exists()).toBe(false)
    expect(wrapper.get('.mobile-header button').attributes('aria-label')).toBe('新建会话')
    expect(wrapper.find('.section-title button').exists()).toBe(false)
    expect(wrapper.findAll('.discovery-side .feature-strip button')).toHaveLength(0)
    await wrapper.get('.guess-card > button').trigger('click')
    await flushPromises()
    const chatCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/chat'))
    expect(JSON.parse(String(chatCall?.[1]?.body))).toMatchObject({ user_id: 'demo_12345678', session_id: null })
    expect(wrapper.text()).toContain('请问客户所属行业？')
    expect(wrapper.text()).toContain('问题衍生')
    expect(localStorage.getItem('dda_session_id')).toBe('ses-1')
    await wrapper.get('.mobile-header button').trigger('click')
    await flushPromises()
    expect(localStorage.getItem('dda_session_id')).toBeNull()
    expect(wrapper.find('.home-panel').exists()).toBe(true)
  })
})

describe('推荐卡片', () => {
  it('展示分数、原因并展开完整综述', async () => {
    const wrapper = mount(RecommendationCard, { props: { item: {
      report_id: 'r1', report_name: '科技企业报告', report_type: '授信尽调', score: 92,
      recommendation_reason: '行业与授信品种匹配', matched_tags: [], unmatched_tags: [],
      report_tags: [{ name: '行业分类', value: '科学研究和技术服务业' }, { name: '备注标签', value: '' }],
      summary: { 客户概况: '经营稳定', 主要风险: ['回款周期较长'] },
    } } })
    expect(wrapper.text()).toContain('92')
    expect(wrapper.text()).not.toContain('经营稳定')
    await wrapper.findAll('.fold-btn')[0].trigger('click')
    expect(wrapper.text()).toContain('经营稳定')
    expect(wrapper.text()).toContain('回款周期较长')
    expect(wrapper.findAll('.fold-btn')[0].attributes('aria-expanded')).toBe('true')
    expect(wrapper.text()).toContain('查看标签（2）')
    await wrapper.findAll('.fold-btn')[1].trigger('click')
    expect(wrapper.text()).toContain('科学研究和技术服务业')
    expect(wrapper.text()).toContain('备注标签')
    expect(wrapper.text()).toContain('—')
  })

  it('点击关联案例时向父组件发送当前报告', async () => {
    const item = { report_id: 'r1', report_name: '报告', report_type: '尽调', score: 80, recommendation_reason: '', matched_tags: [], unmatched_tags: [], summary: {} }
    const wrapper = mount(RecommendationCard, { props: { item, allowRelated: true } })
    await wrapper.get('.related-btn').trigger('click')
    expect(wrapper.emitted('related')?.[0]).toEqual([item])
  })
})

describe('结果组', () => {
  const report=(id:string)=>({report_id:id,report_name:`报告${id}`,report_type:'尽调',score:80,recommendation_reason:'匹配',matched_tags:[],unmatched_tags:[],summary:{}})
  it('前三份直接展示并折叠其余报告', async () => {
    const wrapper=mount(ReportResultsGroup,{props:{items:[1,2,3,4,5].map(x=>report(String(x)))}})
    expect(wrapper.findAll('.recommend-card')).toHaveLength(3)
    expect(wrapper.text()).toContain('查看其余 2 份')
    await wrapper.get('.rest-toggle').trigger('click')
    expect(wrapper.findAll('.recommend-card')).toHaveLength(5)
    expect(wrapper.get('.rest-toggle').attributes('aria-expanded')).toBe('true')
  })
})

describe('运营平台', () => {
  it('固定展示无鉴权风险并掩码显示模型密钥', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.includes('/ops/metrics')) return response({ users: 2, sessions: 3, messages: 8, model_failures: 0, feature_usage: { recommendation: 3 }, recent_conversations: [] })
      if (url.includes('/ops/model-status')) return response({ profile_name: '环境变量配置', model: 'deepseek-chat', healthy: true })
      if (url.includes('/ops/model-profiles')) return response({ items: [{ profile_id: 'm1', name: 'DeepSeek 主配置', provider: 'DeepSeek', base_url: 'https://api.deepseek.com', model: 'deepseek-chat', api_key_masked: 'sk-••••1234', is_active: true }], master_key_configured: true })
      throw new Error(`unexpected request ${url}`)
    }))
    const wrapper = mount(OpsApp)
    await flushPromises()
    expect(wrapper.text()).toContain('应用自身不处理登录')
    expect(wrapper.text()).toContain('用户数')
    await wrapper.findAll('.ops-sidebar nav button')[2].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('sk-••••1234')
    expect(wrapper.text()).not.toContain('sk-sensitive')
  })

  it('支持筛选会话并在抽屉中复盘完整消息', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/ops/metrics')) return response({ users: 1, sessions: 1, messages: 2, model_failures: 0, feature_usage: { recommendation: 1 }, recent_conversations: [] })
      if (url.includes('/ops/model-status')) return response({ profile_name: '环境变量配置', model: 'deepseek-chat', healthy: true, configured: true })
      if (url.includes('/ops/conversations/s1')) return response({ session_id: 's1', title: '科技企业尽调', user_id: 'u1', feature: 'recommendation', updated_at: '2026-08-17 10:00:00', tags: [], messages: [{ id: 1, role: 'user', intent: 'recommendation', content: '推荐科技企业报告', created_at: '2026-08-17 10:00:00', payload: null }] })
      if (url.includes('/ops/conversations/export?')) return response('会话ID,消息内容\ns1,推荐科技企业报告', 200, { 'Content-Disposition': 'attachment; filename="conversation-logs-test.csv"' })
      if (url.includes('/ops/conversations?')) return response({ items: [{ session_id: 's1', title: '科技企业尽调', user_id: 'u1', feature: 'recommendation', message_count: 2, created_at: '2026-08-17 10:00:00', updated_at: '2026-08-17 10:00:00' }], next_cursor: null })
      throw new Error(`unexpected request ${url}`)
    })
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:test') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(OpsApp)
    await flushPromises()
    await wrapper.findAll('.ops-sidebar nav button')[1].trigger('click')
    await flushPromises()
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('days=7'))).toBe(true)
    const threeDays = wrapper.findAll('.time-filter-option').find(button => button.text().includes('过去 3 天'))!
    await threeDays.trigger('click')
    await flushPromises()
    expect(threeDays.attributes('aria-pressed')).toBe('true')
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('days=3'))).toBe(true)
    await wrapper.get('input[placeholder="搜索用户消息内容"]').setValue('科技')
    await wrapper.get('.filter-bar').trigger('submit')
    await flushPromises()
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('keyword=%E7%A7%91%E6%8A%80'))).toBe(true)
    await wrapper.get('.export-button').trigger('click')
    await flushPromises()
    const exportUrl = String(fetchMock.mock.calls.find(([url]) => String(url).includes('/ops/conversations/export?'))?.[0])
    expect(exportUrl).toContain('days=3')
    expect(exportUrl).toContain('keyword=%E7%A7%91%E6%8A%80')
    expect(exportUrl).not.toContain('limit=')
    expect(URL.createObjectURL).toHaveBeenCalled()
    await wrapper.get('.row-action').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('推荐科技企业报告')
    expect(wrapper.get('.ops-drawer').attributes('role')).toBe('dialog')
  })
})
