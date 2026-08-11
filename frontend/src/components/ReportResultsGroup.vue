<script setup lang="ts">
import { computed, ref } from 'vue'
import RecommendationCard from './RecommendationCard.vue'

const props = defineProps<{ items: any[], allowRelated?: boolean }>()
const emit = defineEmits<{ related: [item: any] }>()
const restOpen = ref(false)
const primary = computed(() => props.items.slice(0, 3))
const rest = computed(() => props.items.slice(3))
</script>

<template>
  <section v-if="items?.length" class="report-results">
    <div class="result-group-title"><b>报告结果</b><span>共 {{ items.length }} 份</span></div>
    <RecommendationCard v-for="item in primary" :key="item.report_id" :item="item" :allow-related="allowRelated" @related="emit('related', $event)" />
    <button v-if="rest.length" class="rest-toggle" :aria-expanded="restOpen" @click="restOpen = !restOpen">
      {{ restOpen ? '收起其余报告' : `查看其余 ${rest.length} 份` }} <span>{{ restOpen ? '⌃' : '⌄' }}</span>
    </button>
    <div v-if="restOpen" class="remaining-results">
      <RecommendationCard v-for="item in rest" :key="item.report_id" :item="item" compact :allow-related="false" />
    </div>
  </section>
</template>
