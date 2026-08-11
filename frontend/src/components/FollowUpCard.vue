<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{ followUp: any }>()
const emit = defineEmits<{
  apply: [selections: { tag_name: string, value: string }[]]
  skip: []
  custom: [tagName: string]
  remove: [tagName: string]
}>()
const showMore = ref(false)
const selected = ref<Record<string, string>>({})
const groups = computed(() => showMore.value ? props.followUp.groups : props.followUp.groups.slice(0, 1))
function select(tagName: string, value: string) { selected.value = { ...selected.value, [tagName]: value } }
function apply() {
  const values = groups.value.flatMap((group: any) => selected.value[group.tag_name] ? [{ tag_name: group.tag_name, value: selected.value[group.tag_name] }] : [])
  if (values.length) emit('apply', values)
}
</script>

<template>
  <aside class="follow-up-card">
    <div class="follow-up-head"><div><b>{{ followUp.title }}</b><p>{{ followUp.prompt }}</p></div><small v-if="followUp.remaining_rounds">还可细化 {{ followUp.remaining_rounds }} 轮</small></div>
    <div v-for="group in groups" :key="group.tag_name" class="follow-up-group">
      <strong>{{ group.label }}</strong>
      <div class="option-grid">
        <button v-for="option in group.options" :key="option.value" :class="{ selected: selected[group.tag_name] === option.value }" @click="select(group.tag_name, option.value)">
          {{ option.label }}<small v-if="option.count">{{ option.count }}份</small>
        </button>
      </div>
    </div>
    <div class="follow-up-actions">
      <button v-if="followUp.allow_more && followUp.groups.length > 1" class="secondary-action" :aria-expanded="showMore" @click="showMore = !showMore">{{ showMore ? '收起条件' : '更多条件' }}</button>
      <button v-if="followUp.allow_custom" class="secondary-action" @click="emit('custom', groups[0]?.tag_name || '')">自定义输入</button>
      <button v-if="followUp.removable_tag" class="secondary-action danger" @click="emit('remove', followUp.removable_tag)">移除“{{ followUp.removable_tag }}”</button>
      <button v-if="followUp.allow_skip" class="secondary-action" @click="emit('skip')">暂不补充</button>
      <button v-if="Object.keys(selected).length" class="apply-action" @click="apply">应用条件</button>
    </div>
  </aside>
</template>
