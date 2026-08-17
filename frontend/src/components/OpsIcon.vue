<script setup lang="ts">
defineProps<{ name: string, size?: number }>()
</script>

<template>
  <svg class="ops-icon" :width="size || 18" :height="size || 18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <template v-if="name === 'dashboard'"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></template>
    <template v-else-if="name === 'message'"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/><path d="M8 8h8M8 12h5"/></template>
    <template v-else-if="name === 'cpu'"><rect x="7" y="7" width="10" height="10" rx="2"/><path d="M9 1v3m6-3v3M9 20v3m6-3v3M20 9h3m-3 6h3M1 9h3m-3 6h3M10 10h4v4h-4z"/></template>
    <template v-else-if="name === 'refresh'"><path d="M20 6v5h-5M4 18v-5h5"/><path d="M18.5 9A7 7 0 0 0 6 6.5L4 9m2 6a7 7 0 0 0 12 2.5L20 15"/></template>
    <template v-else-if="name === 'users'"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></template>
    <template v-else-if="name === 'sessions'"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/></template>
    <template v-else-if="name === 'send'"><path d="m22 2-7 20-4-9-9-4zM22 2 11 13"/></template>
    <template v-else-if="name === 'alert'"><path d="M10.3 2.9 1.8 17a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 2.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4m0 4h.01"/></template>
    <template v-else-if="name === 'shield'"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></template>
    <template v-else-if="name === 'arrow'"><path d="M5 12h14m-6-6 6 6-6 6"/></template>
    <template v-else-if="name === 'search'"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></template>
    <template v-else-if="name === 'reset'"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></template>
    <template v-else-if="name === 'plus'"><path d="M12 5v14M5 12h14"/></template>
    <template v-else-if="name === 'edit'"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z"/></template>
    <template v-else-if="name === 'test'"><path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.7 3h10.6A2 2 0 0 0 19 18l-5-9V3"/><path d="M8 15h8"/></template>
    <template v-else-if="name === 'check'"><path d="m20 6-11 11-5-5"/></template>
    <template v-else-if="name === 'trash'"><path d="M3 6h18M8 6V4h8v2m3 0-1 15H6L5 6m5 4v7m4-7v7"/></template>
    <template v-else-if="name === 'close'"><path d="M18 6 6 18M6 6l12 12"/></template>
    <template v-else-if="name === 'menu'"><path d="M4 6h16M4 12h16M4 18h16"/></template>
    <template v-else-if="name === 'clock'"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></template>
    <template v-else-if="name === 'download'"><path d="M12 3v12m-5-5 5 5 5-5"/><path d="M5 20h14"/></template>
    <template v-else-if="name === 'key'"><circle cx="8" cy="15" r="4"/><path d="m11 12 9-9m-3 0h3v3"/></template>
    <template v-else><circle cx="12" cy="12" r="9"/></template>
  </svg>
</template>
