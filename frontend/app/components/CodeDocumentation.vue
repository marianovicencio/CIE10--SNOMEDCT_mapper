<script setup lang="ts">
import type { CodeDocument } from '~/types/consultation'
const props = defineProps<{ document: CodeDocument, loading: boolean, error?: string }>()
defineEmits<{ more: [] }>()
const tab = ref('tabular')
watch(() => props.document.code, () => { tab.value = 'tabular' })
const tabs = [{label:'Lista tabular',value:'tabular'},{label:'Manual',value:'manual'},{label:'Índice',value:'index'}]
const groups = [{label:'Inclusiones',key:'inclusions'},{label:'Exclusiones',key:'exclusions'},{label:'Instrucciones',key:'instructions'},{label:'Notas',key:'notes'},{label:'Contexto general',key:'general_context'}]
const entries = computed(() => tab.value === 'manual' ? props.document.manual_context : [...props.document.index_context,...props.document.shared_context])
</script>
<template>
  <section class="cd-document" aria-label="Información del código CIE-10">
    <UTabs v-model="tab" :items="tabs" :content="false" size="sm" />
    <div v-if="tab === 'tabular'" class="cd-content">
      <details v-for="group in groups" :key="group.key" class="cd-group">
        <summary>{{ group.label }} <span>{{ document.tabular[group.key]?.length ?? 0 }}</span></summary>
        <p v-if="!document.tabular[group.key]?.length" class="cd-muted">Sin registros.</p>
        <article v-for="(item,index) in document.tabular[group.key]" :key="index" class="cd-entry">
          <strong v-if="item.title">{{ item.title }}</strong><p v-if="item.text">{{ item.text }}</p>
          <p v-for="note in item.numbered_notes" :key="note.text">{{ note.text }}</p>
          <small v-if="item.inherited">Heredado de {{ item.origin }}</small>
          <small v-for="ref in item.references || (item.reference ? [item.reference] : [])" :key="ref.source">{{ ref.source }}</small>
        </article>
      </details>
    </div>
    <div v-else class="cd-content">
      <p v-if="!entries.length" class="cd-muted">Sin registros en esta página.</p>
      <article v-for="(item,index) in entries" :key="index" class="cd-entry">
        <strong v-if="item.title || item.term || item.section">{{ item.title || item.term || ('Sección '+item.section) }}</strong>
        <p v-if="item.text">{{ item.text }}</p><small>{{ item.reference?.source }}</small>
      </article>
      <UButton v-if="document.pagination.next_offset != null" color="neutral" variant="outline" size="xs" :loading="loading" @click="$emit('more')">Cargar más registros</UButton>
      <p v-if="error" role="alert" class="cd-muted">{{ error }}</p>
    </div>
    <details class="cd-technical">
      <summary>Datos técnicos de CIE-10</summary>
      <p>{{ document.edition }} · {{ document.classification.reference?.source }}</p>
      <div class="cd-links">
        <UButton :to="'/api/raw/cie10/'+document.code" target="_blank" rel="noopener noreferrer" icon="i-lucide-braces" color="neutral" variant="outline" size="xs">Ver JSON</UButton>
        <UButton :to="'/api/raw/cie10/'+document.code+'?view=evidence'" target="_blank" rel="noopener noreferrer" color="neutral" variant="link" size="xs">JSON con trazabilidad</UButton>
      </div>
    </details>
  </section>
</template>
<style scoped>
.cd-document { min-width:0; }
.cd-content { padding-top:12px; }
.cd-group { border-top:1px solid var(--line); padding:10px 0; }
.cd-group summary,.cd-technical summary { cursor:pointer; font-size:13px; }
.cd-group summary span { color:var(--muted); margin-left:6px; }
.cd-entry { padding:10px 0; font-size:13px; line-height:1.65; overflow-wrap:anywhere; }
.cd-entry p { margin:4px 0; white-space:pre-line; }
.cd-entry small,.cd-muted { display:block; font-size:12px; color:var(--muted); }
.cd-technical { border-top:1px solid var(--line); margin-top:12px; padding-top:12px; }
.cd-technical p { margin:10px 0; font-size:12px; color:var(--muted); }
.cd-links { display:flex; flex-wrap:wrap; gap:8px; }
</style>
