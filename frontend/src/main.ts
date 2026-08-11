import { createApp, h } from 'vue'
import { createRouter, createWebHistory, RouterView } from 'vue-router'
import MobileApp from './pages/MobileApp.vue'
import OpsApp from './pages/OpsApp.vue'
import './styles.css'
import './unified.css'

const router = createRouter({ history: createWebHistory(import.meta.env.BASE_URL), routes: [
  { path: '/', component: MobileApp }, { path: '/ops', component: OpsApp },
]})
createApp({ render: () => h(RouterView) }).use(router).mount('#app')
