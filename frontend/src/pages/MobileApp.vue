<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, post } from '../api'
import ReportResultsGroup from '../components/ReportResultsGroup.vue'

const userId = ref(localStorage.getItem('dda_user_id') || `demo_${crypto.randomUUID().slice(0, 8)}`)
localStorage.setItem('dda_user_id', userId.value)
const bootstrap = ref<any>(null), homeSuggestions = ref<any[]>([])
const messages = ref<any[]>([]), sessionId = ref<string|null>(localStorage.getItem('dda_session_id')), input = ref('')
const loading = ref(false), error = ref('')
const featureIcons:Record<string,string>={recommendation:'✦',filter:'⌕',statistics:'▥',qa:'●',spark:'✦',chart:'▥',chat:'●'}
const featureNames:Record<string,string>={recommendation:'案例推荐',filter:'多维筛选',statistics:'数据统计',qa:'比赛问答',greeting:'助手问候',unsupported:'能力边界'}
const assistantIntro = computed(() => String(bootstrap.value?.assistant?.intro || '').replace(/尽调(?:报告)?助手/g, '立功竞赛助手'))

async function init(){
  bootstrap.value=await api(`/ui/bootstrap?user_id=${encodeURIComponent(userId.value)}`)
  homeSuggestions.value=bootstrap.value.default_suggestions
  if(sessionId.value){
    try{
      const conversation:any=await api(`/conversations/${encodeURIComponent(sessionId.value)}`)
      if(conversation.user_id!==userId.value)throw new Error('会话用户不一致')
      messages.value=conversation.messages.map((m:any)=>({role:m.role,content:m.content,payload:m.payload,suggestions:[]}))
    }catch{
      sessionId.value=null
      localStorage.removeItem('dda_session_id')
    }
  }
  await refreshSuggestions()
}
async function refreshSuggestions(attach=false){
  try{
    const r:any=await post('/suggestions',{user_id:userId.value,session_id:sessionId.value})
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
    localStorage.setItem('dda_session_id',body.session_id)
    messages.value.push({role:'assistant',content:body.assistant_message,payload:body,suggestions:[]})
    await refreshSuggestions(true)
  }catch(e:any){error.value=e.message}finally{loading.value=false}
}
async function send(text=input.value){
  if(!text?.trim()||loading.value)return
  input.value=''
  await appendResponse({message:text},text)
}
function openFeature(card:any){messages.value.push({role:'assistant',content:card.assistant_example,payload:{guide:true,intent:card.id,examples:card.input_examples},suggestions:[]})}
async function related(item:any){if(sessionId.value)await appendResponse({action:{type:'related_reports',report_id:item.report_id}},`查看“${item.report_name}”的关联案例`)}
function newChat(){sessionId.value=null;localStorage.removeItem('dda_session_id');messages.value=[];error.value='';refreshSuggestions()}
onMounted(init)
</script>

<template>
  <main class="mobile-shell">
    <header class="mobile-header"><span class="header-spacer" aria-hidden="true"></span><div><strong>立功竞赛助手</strong><small>统一智能对话服务</small></div><button aria-label="新建会话" @click="newChat">＋</button></header>
    <div class="mobile-scroll">
      <section v-if="bootstrap&&!messages.length" class="home-panel">
        <div class="bot-line"><div class="bot-avatar">立</div><div class="intro-bubble">{{assistantIntro}}</div></div>
        <div class="discovery-grid">
          <button class="hero-card" @click="openFeature(bootstrap.feature_cards[0])"><span>智能案例推荐</span><strong>找到更合适的<br/>尽调案例</strong><em>立即体验 →</em></button>
          <div class="discovery-side">
            <section class="guess-card"><div class="section-title"><b>猜你想问</b></div><button v-for="q in homeSuggestions" :key="q.intent+q.text" @click="send(q.text)"><span class="suggestion-icon">{{featureIcons[q.intent]}}</span><span>{{q.text}}</span></button></section>
            <div class="feature-strip"><button v-for="card in bootstrap.feature_cards.slice(1)" :key="card.id" @click="openFeature(card)"><span class="feature-icon">{{featureIcons[card.icon]||'•'}}</span><b>{{card.title}}</b><small>{{card.description}}</small></button></div>
          </div>
        </div>
      </section>

      <section v-if="messages.length" class="chat-list">
        <template v-for="(m,i) in messages" :key="i">
          <div :class="['message',m.role]"><div class="bubble"><span v-if="m.payload?.intent" class="intent-label">{{featureNames[m.payload.intent]||'助手'}}</span>{{m.content}}</div></div>
          <div v-if="m.payload?.guide" class="guide-card"><b>{{featureNames[m.payload.intent]}}输入案例</b><button v-for="x in m.payload.examples" :key="x" @click="send(x)">“{{x}}”</button><small>点击案例可直接发送，也可以在下方输入自己的问题。</small></div>
          <ReportResultsGroup :items="m.payload?.recommendations||[]" :allow-related="m.payload?.status==='recommendations'" @related="related"/>
          <div v-if="m.payload?.answer" class="answer-note">⚠ {{m.payload.answer.disclaimer}}</div>
          <div v-if="m.role==='assistant'&&m.suggestions?.length" class="message-suggestions"><small>问题衍生</small><button v-for="q in m.suggestions" :key="q.intent+q.text" @click="send(q.text)"><span>{{featureIcons[q.intent]}}</span>{{q.text}}</button></div>
        </template>
        <div v-if="loading" class="typing">助手正在思考<span>•••</span></div><p v-if="error" class="error">{{error}}</p>
      </section>
    </div>
    <footer class="composer"><div class="input-row"><input v-model="input" placeholder="推荐、筛选、统计或询问比赛…" @keyup.enter="send()"/><button :disabled="loading" @click="send()">➤</button></div></footer>
  </main>
</template>
