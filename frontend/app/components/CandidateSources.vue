<script setup lang="ts">
import type { Candidate, CodeDocument } from '~/types/consultation'
import { documentTitle } from '~/types/consultation'
import type { ExplanationState } from '~/types/explanation'
const props=defineProps<{candidate:Candidate,document:CodeDocument,state?:ExplanationState,version?:string,focusRefs:string[]}>()
defineEmits<{all:[]}>()
type Source={id:string,label:string,text:string,origin:string,support?:boolean}
const sources=computed(()=>{
  const rows=new Map<string,Source>()
  const release=props.version?.split('/').at(-1)?.replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3') || ''
  const origin='SNOMED CT · edición española '+release
  const add=(row:Source)=>{
    const old=rows.get(row.id)
    if(!old || row.text.length>old.text.length) rows.set(row.id,row)
  }
  add({id:'cie-title',label:'Título y alcance CIE-10',text:documentTitle(props.document),origin:props.document.classification.reference?.source||props.document.edition})
  add({id:'snomed-term',label:'Descripción SNOMED CT',text:props.candidate.term,origin})
  for(const item of props.candidate.review?.citations??[])add({id:item.id,label:item.label||(item.type==='INPUT'?'Diagnóstico aportado':item.volume?'CIE-10 · tomo '+item.volume:item.type==='SNOMED'?'SNOMED CT':'CIE-10'),text:item.text||'',origin:item.type==='SNOMED'?origin:item.provenance||''})
  const result=props.state?.result
  for(const quote of result?.analysis?.quotes??[]){
    const meta=result?.evidence?.find(x=>x.id===quote.evidence_id)
    add({id:quote.evidence_id,label:meta?.label||'Fuente de la explicación',text:meta?.reading_text||quote.text,origin:meta?.type==='SNOMED'?origin:meta?.source||''})
  }
  for(const item of result?.manual_context?.items??[])add({id:item.id,label:item.title||'Manual · sección '+item.section,text:item.text,origin:item.provenance,support:!item.cited})
  for(const item of result?.index_context?.items??[])add({id:item.id,label:item.route.join(' > ')||'Índice alfabético',text:item.text,origin:item.provenance,support:!item.cited})
  return [...rows.values()]
})
const visible=computed(()=>props.focusRefs.length?sources.value.filter(x=>props.focusRefs.includes(x.id)):sources.value)
</script>
<template>
  <section class="cs-sources" aria-label="Fuentes del candidato">
    <div v-if="focusRefs.length" class="cs-filter"><span>Fuentes de la afirmación seleccionada</span><UButton color="neutral" variant="link" size="xs" @click="$emit('all')">Mostrar todas</UButton></div>
    <p v-if="!visible.length" class="cs-empty">No se recuperó el texto de estas fuentes.</p>
    <details v-for="source in visible" :key="source.id" class="cs-entry" :open="focusRefs.length>0">
      <summary>{{ source.label }}<small v-if="source.support">Contexto de apoyo</small></summary>
      <p>{{ source.text }}</p><small>{{ source.origin }}</small>
    </details>
  </section>
</template>
<style scoped>
.cs-sources { min-width:0; }
.cs-entry { padding:12px 0; border-bottom:1px solid var(--line); }
.cs-entry summary { cursor:pointer; font-size:13px; line-height:1.5; overflow-wrap:anywhere; }
.cs-entry p { white-space:pre-line; overflow-wrap:anywhere; margin:12px 0 8px; line-height:1.7; font-size:13px; }
.cs-entry small { display:block; color:var(--muted); font-size:11px; margin-top:4px; }
.cs-filter { display:flex; align-items:center; flex-wrap:wrap; justify-content:space-between; gap:8px; font-size:12px; color:var(--muted); margin-bottom:8px; }
.cs-empty { color:var(--muted); font-size:13px; }
</style>
