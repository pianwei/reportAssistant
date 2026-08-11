<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { api, post } from '../api'
import FollowUpCard from '../components/FollowUpCard.vue'
import ReportResultsGroup from '../components/ReportResultsGroup.vue'

const userId = ref(localStorage.getItem('dda_user_id') || `demo_${crypto.randomUUID().slice(0, 8)}`)
localStorage.setItem('dda_user_id', userId.value)
const bootstrap = ref<any>(null), homeSuggestions = ref<any[]>([]), batchId = ref<string|null>(null)
const messages = ref<any[]>([]), sessionId = ref<string|null>(null), input = ref(''), inputEl = ref<HTMLInputElement|null>(null)
const inputPlaceholder = ref('推荐、筛选、统计或询问比赛…')
const loading = ref(false), error = ref(''), historyOpen = ref(false), history = ref<any[]>([])
const featureIcons:Record<string,string>={recommendation:'✦',filter:'⌕',statistics:'▥',qa:'●',spark:'✦',chart:'▥',chat:'●'}
const featureNames:Record<string,string>={recommendation:'案例推荐',filter:'多维筛选',statistics:'数据统计',qa:'比赛问答'}

async function init(){
  bootstrap.value=await api(`/ui/bootstrap?user_id=${encodeURIComponent(userId.value)}`)
  homeSuggestions.value=bootstrap.value.default_suggestions
  await refreshSuggestions(false)
}
async function refreshSuggestions(rotate=true, attach=false){
  try{
    const r:any=await post('/suggestions',{user_id:userId.value,session_id:sessionId.value,previous_batch_id:rotate?batchId.value:null})
    batchId.value=r.batch_id
    if(attach){
      const latest=[...messages.value].reverse().find((m:any)=>m.role==='assistant')
      if(latest) latest.suggestions=r.suggestions
    }else homeSuggestions.value=r.suggestions
  }catch{}
}
async function appendResponse(request:any, userLabel?:string){
  if(loading.value)return
  if(userLabel) messages.value.push({role:'user',content:userLabel})
  loading.value=true;error.value=''
  try{
    const body:any=await post('/chat',{user_id:userId.value,session_id:sessionId.value,...request})
    sessionId.value=body.session_id
    messages.value.push({role:'assistant',content:body.assistant_message,payload:body,suggestions:[]})
    await refreshSuggestions(false,true)
  }catch(e:any){error.value=e.message}finally{loading.value=false}
}
async function send(text=input.value){
  if(!text?.trim()||loading.value)return
  input.value='';inputPlaceholder.value='推荐、筛选、统计或询问比赛…'
  await appendResponse({message:text},text)
}
function openFeature(card:any){messages.value.push({role:'assistant',content:card.assistant_example,payload:{guide:true,intent:card.id,examples:card.input_examples},suggestions:[]})}
async function related(item:any){if(sessionId.value)await appendResponse({action:{type:'related_reports',report_id:item.report_id}},`查看“${item.report_name}”的关联案例`)}
async function applyRefinement(selections:any[]){
  const label=`补充条件：${selections.map(x=>`${x.tag_name}为${x.value}`).join('，')}`
  await appendResponse({action:{type:'apply_refinement',selections}},label)
}
async function skipRefinement(){await appendResponse({action:{type:'skip_refinement'}},'暂不补充')}
async function removeTag(tagName:string){await appendResponse({action:{type:'remove_tag',tag_name:tagName}},`移除条件：${tagName}`)}
async function customInput(tagName:string){inputPlaceholder.value=tagName?`请输入${tagName}…`:'请输入补充条件…';await nextTick();inputEl.value?.focus()}
async function loadHistory(){const r:any=await api(`/users/${userId.value}/conversations`);history.value=r.items;historyOpen.value=true}
async function restore(id:string){
  const r:any=await api(`/conversations/${id}`);sessionId.value=id
  messages.value=r.messages.map((m:any)=>({role:m.role,content:m.content,payload:m.payload,suggestions:[]}))
  historyOpen.value=false;await refreshSuggestions(false,true)
}
function newChat(){sessionId.value=null;messages.value=[];error.value='';batchId.value=null;inputPlaceholder.value='推荐、筛选、统计或询问比赛…';refreshSuggestions(false)}
onMounted(init)
</script>

<template>
  <main class="mobile-shell">
    <header class="mobile-header"><button aria-label="新建会话" @click="newChat">＋</button><div><strong>尽调报告助手</strong><small>统一智能对话服务</small></div><button aria-label="历史记录" @click="loadHistory">◷</button></header>
    <div class="mobile-scroll">
      <section v-if="bootstrap&&!messages.length" class="home-panel">
        <div class="bot-line"><div class="bot-avatar">尽</div><div class="intro-bubble">{{bootstrap.assistant.intro}}</div></div>
        <div class="discovery-grid">
          <button class="hero-card" @click="openFeature(bootstrap.feature_cards[0])"><span>智能案例推荐</span><strong>找到更合适的<br/>尽调案例</strong><em>立即体验 →</em></button>
          <section class="guess-card"><div class="section-title"><b>猜你想问</b><button @click="refreshSuggestions(true)">↻ 换一批</button></div><button v-for="q in homeSuggestions" :key="q.intent+q.text" @click="send(q.text)"><span class="suggestion-icon">{{featureIcons[q.intent]}}</span><span>{{q.text}}</span></button></section>
        </div>
        <div class="feature-strip"><button v-for="card in bootstrap.feature_cards" :key="card.id" @click="openFeature(card)"><span class="feature-icon">{{featureIcons[card.icon]||'•'}}</span><b>{{card.title}}</b><small>{{card.description}}</small></button></div>
      </section>

      <section v-if="messages.length" class="chat-list">
        <template v-for="(m,i) in messages" :key="i">
          <div :class="['message',m.role]"><div class="bubble"><span v-if="m.payload?.intent" class="intent-label">{{featureNames[m.payload.intent]||'助手'}}</span>{{m.content}}</div></div>
          <div v-if="m.payload?.guide" class="guide-card"><b>{{featureNames[m.payload.intent]}}输入案例</b><button v-for="x in m.payload.examples" :key="x" @click="send(x)">“{{x}}”</button><small>点击案例可直接发送，也可以在下方输入自己的问题。</small></div>
          <div v-if="m.payload?.question&&!m.payload?.follow_up" class="quick-confirm"><button v-for="x in m.payload.question.examples" :key="x" @click="send(x)">{{x}}</button><button v-if="m.payload.question.skippable" @click="send('跳过')">跳过</button><button v-if="m.payload.question.allow_finish" class="finish-action" @click="send(m.payload.intent==='filter'?'直接筛选':'按现有信息生成')">按现有信息生成</button></div>
          <ReportResultsGroup :items="m.payload?.recommendations||[]" :allow-related="m.payload?.status==='recommendations'" @related="related"/>
          <FollowUpCard v-if="m.payload?.follow_up" :follow-up="m.payload.follow_up" @apply="applyRefinement" @skip="skipRefinement" @custom="customInput" @remove="removeTag"/>
          <div v-if="m.payload?.answer" class="answer-note">⚠ {{m.payload.answer.disclaimer}}</div>
          <div v-if="m.role==='assistant'&&m.suggestions?.length" class="message-suggestions"><small>猜你想问</small><button v-for="q in m.suggestions" :key="q.intent+q.text" @click="send(q.text)"><span>{{featureIcons[q.intent]}}</span>{{q.text}}</button></div>
        </template>
        <div v-if="loading" class="typing">助手正在思考<span>•••</span></div><p v-if="error" class="error">{{error}}</p>
      </section>
    </div>
    <footer class="composer"><div class="input-row"><input ref="inputEl" v-model="input" :placeholder="inputPlaceholder" @keyup.enter="send()"/><button :disabled="loading" @click="send()">➤</button></div></footer>
    <div v-if="historyOpen" class="drawer-mask" @click.self="historyOpen=false"><aside class="history-drawer"><div class="panel-head"><h2>历史会话</h2><button @click="historyOpen=false">×</button></div><button v-for="item in history" :key="item.session_id" class="history-item" @click="restore(item.session_id)"><b>{{item.title}}</b><small>{{item.updated_at}} · {{item.message_count}}条消息 · {{item.feature}}</small></button><p v-if="!history.length" class="empty">暂无历史会话</p></aside></div>
  </main>
</template>
