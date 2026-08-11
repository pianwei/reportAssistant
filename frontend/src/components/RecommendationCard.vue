<script setup lang="ts">
import { ref } from 'vue'
defineProps<{ item: any, allowRelated?: boolean }>()
const emit = defineEmits<{ related: [item: any] }>()
const expanded = ref(false)
</script>
<template>
  <article class="recommend-card">
    <div class="recommend-head"><div><span class="eyebrow">{{ item.report_type }}</span><h3>{{ item.report_name }}</h3></div><div class="score">{{ item.score }}<small>匹配分</small></div></div>
    <p class="reason">{{ item.recommendation_reason }}</p>
    <div class="tag-row"><span v-for="tag in item.matched_tags" :key="tag.name" class="tag success">✓ {{ tag.name }}</span><span v-for="tag in item.unmatched_tags" :key="tag.name" class="tag muted">{{ tag.name }}</span></div>
    <div class="recommend-actions"><button class="text-btn" @click="expanded = !expanded">{{ expanded ? '收起详情' : '查看案例详情' }} <span>{{ expanded ? '⌃' : '⌄' }}</span></button><button v-if="allowRelated" class="related-btn" @click="emit('related', item)">推荐关联案例</button></div>
    <div v-if="expanded" class="summary-grid">
      <section v-for="(value,key) in item.summary" :key="key"><h4>{{ key }}</h4><ul v-if="Array.isArray(value)"><li v-for="line in value" :key="line">{{ line }}</li></ul><p v-else>{{ value }}</p></section>
    </div>
  </article>
</template>
