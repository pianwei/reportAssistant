<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ item: any, allowRelated?: boolean, compact?: boolean }>()
const emit = defineEmits<{ related: [item: any] }>()
const detailsOpen = ref(false)
const tagsOpen = ref(false)
</script>

<template>
  <article :class="['recommend-card', { compact }]">
    <div class="recommend-head">
      <div class="report-title"><span class="eyebrow">{{ item.report_type }}</span><h3>{{ item.report_name }}</h3></div>
      <div v-if="item.score !== undefined" class="score">{{ item.score }}<small>匹配分</small></div>
    </div>
    <p v-if="item.recommendation_reason" class="reason">{{ item.recommendation_reason }}</p>
    <div class="recommend-actions">
      <button class="fold-btn" :aria-expanded="detailsOpen" @click="detailsOpen = !detailsOpen">
        <span>{{ detailsOpen ? '收起详情' : '查看详情' }}</span><b>{{ detailsOpen ? '⌃' : '⌄' }}</b>
      </button>
      <button class="fold-btn" :aria-expanded="tagsOpen" @click="tagsOpen = !tagsOpen">
        <span>查看标签（{{ (item.matched_tags?.length || 0) + (item.unmatched_tags?.length || 0) }}）</span><b>{{ tagsOpen ? '⌃' : '⌄' }}</b>
      </button>
      <button v-if="allowRelated" class="related-btn" @click="emit('related', item)">关联案例</button>
    </div>
    <div v-if="tagsOpen" class="tag-row">
      <span v-for="tag in item.matched_tags" :key="`hit-${tag.name}`" class="tag success">✓ {{ tag.name }}：{{ tag.value }}</span>
      <span v-for="tag in item.unmatched_tags" :key="`miss-${tag.name}`" class="tag muted">{{ tag.name }}：{{ tag.value }}</span>
    </div>
    <div v-if="detailsOpen" class="summary-grid">
      <section v-for="(value,key) in item.summary" :key="key"><h4>{{ key }}</h4><ul v-if="Array.isArray(value)"><li v-for="line in value" :key="line">{{ line }}</li></ul><p v-else>{{ value }}</p></section>
    </div>
  </article>
</template>
