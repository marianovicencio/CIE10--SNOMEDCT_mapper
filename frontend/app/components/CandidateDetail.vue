<script setup lang="ts">
import type { Candidate, CodeDocument, SearchResult } from '~/types/consultation'
import { candidateNotice } from '~/types/consultation'
import type { ExplanationState } from '~/types/explanation'
const props=defineProps<{candidate:Candidate,document:CodeDocument,result:SearchResult,state?:ExplanationState,disabled:boolean,available:boolean,contextLoading:boolean,contextError:string,needsConsent:boolean,otherExplanationRunning:boolean}>()
defineEmits<{generate:[],regenerate:[],back:[]}>()
const tab=ref('comparison')
const sourceRefs=ref<string[]>([])
const tabs=[{label:'Comparación',value:'comparison'},{label:'Explicación',value:'explanation'},{label:'Fuentes',value:'sources'},{label:'Datos técnicos',value:'technical'}]
const automaticSummary=computed(()=>props.candidate.review?.automatic_comparison?.text || props.state?.result?.automatic_comparison?.text)
const notice=computed(()=>candidateNotice(props.candidate))
const release=computed(()=>props.result.target?.version.split('/').at(-1)?.replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3'))
watch(()=>props.candidate.id,()=>{tab.value='comparison';sourceRefs.value=[]})
function showSources(refs:string[]){sourceRefs.value=refs;tab.value='sources'}
function selectTab(value:unknown){tab.value=String(value);sourceRefs.value=[]}
</script>
<template>
  <section id="candidate-detail" data-tour="candidate-detail" class="cd-detail" aria-label="Detalle del candidato" tabindex="-1">
    <header class="cd-header">
      <UButton class="cd-back" icon="i-lucide-arrow-left" color="neutral" variant="ghost" size="xs" @click="$emit('back')">Volver a candidatos</UButton>
      <p class="cd-eyebrow">CANDIDATO SNOMED CT</p><h2>{{ candidate.term }}</h2>
      <p v-if="automaticSummary" class="cd-summary"><strong>Comparación automática</strong>{{ automaticSummary }}</p>
      <p v-if="notice" class="cd-notice" :data-tone="notice.tone">{{ notice.label }}</p>
    </header>
    <div class="cd-tabs" role="group" aria-label="Secciones del candidato"><button v-for="item in tabs" :key="item.value" type="button" :data-tour="'tab-'+item.value" :aria-pressed="tab===item.value" :class="{active:tab===item.value}" @click="selectTab(item.value)">{{ item.label }}</button></div>
    <div class="cd-body">
      <template v-if="tab==='comparison'">
        <p v-if="contextLoading" role="status" class="cd-loading"><UIcon name="i-lucide-loader-circle" class="animate-spin" /> Revisando la información del candidato…</p>
        <CandidateContextReview v-else-if="candidate.review" :key="candidate.id" :review="candidate.review" />
        <p v-else class="cd-muted">{{ contextError?'La comparación no está disponible. Puedes reintentarla desde la lista de candidatos.':'No se recuperó una comparación para este candidato.' }}</p>
      </template>
      <template v-else-if="tab==='explanation'">
        <div v-if="candidate.review?.status==='excluded_by_explicit_constraint'" class="cd-excluded"><h3>Hay un conflicto con la evidencia</h3><p>{{ candidate.review.constraint?.justification }}</p><UButton color="neutral" variant="outline" size="xs" @click="tab='comparison'">Consultar la diferencia</UButton></div>
        <template v-else>
          <p v-if="needsConsent" class="cd-notice" data-tone="warning">Autoriza el envío al proveedor externo indicado en «Opciones avanzadas» para generar esta explicación.</p>
          <p v-else-if="otherExplanationRunning" class="cd-muted" role="status">Hay otra explicación en curso. Puedes seguir consultando las fuentes mientras termina.</p>
          <CandidateExplanation :state="state" :disabled="disabled" :available="available" @generate="$emit('generate')" @regenerate="$emit('regenerate')" @sources="showSources" />
        </template>
      </template>
      <CandidateSources v-else-if="tab==='sources'" :candidate="candidate" :document="document" :state="state" :version="result.target?.version" :focus-refs="sourceRefs" @all="sourceRefs=[]" />
      <section v-else aria-label="Datos técnicos del candidato" class="cd-technical">
        <dl><div><dt>Identificador SNOMED CT</dt><dd>{{ candidate.id }}</dd></div><div><dt>Edición española</dt><dd>{{ release }}</dd></div><div><dt>Actividad del concepto</dt><dd>{{ candidate.active?'Activo':'No verificada' }}</dd></div><div><dt>Posición de búsqueda</dt><dd>{{ candidate.retrievalRank??candidate.rank }}</dd></div></dl>
        <div class="cd-json"><UButton :to="'/api/raw/snomed/'+candidate.id+(result.target?.version?'?version='+encodeURIComponent(result.target.version):'')" target="_blank" rel="noopener noreferrer" icon="i-lucide-braces" color="neutral" variant="outline" size="xs">Ver JSON FHIR</UButton></div>
        <details><summary>Recuperación del candidato</summary>
          <article v-for="(match,index) in candidate.matches" :key="index"><strong>{{ match.method==='lexical'?'Búsqueda textual':'SAPBERT' }} · posición {{ match.rank }}</strong><p>{{ match.term }}</p><small>Consulta: {{ result.queries?.find(q=>q.id===match.query_id)?.text }}</small></article>
        </details>
        <details v-if="state?.result"><summary>Generación de la explicación</summary><dl><div><dt>Método</dt><dd>{{ state.result.generation_method }}</dd></div><div v-if="state.result.model"><dt>Modelo</dt><dd>{{ state.result.model }}</dd></div></dl></details>
      </section>
    </div>
  </section>
</template>
<style scoped>
.cd-detail { min-width:0; outline:none; }
.cd-detail:focus-visible { outline:2px solid #777; outline-offset:3px; }
.cd-header { padding:20px 20px 15px; }
.cd-eyebrow { font-size:10px; letter-spacing:.1em; color:var(--muted); margin:0 0 8px; }
.cd-header h2 { font-size:17px; line-height:1.5; overflow-wrap:anywhere; margin:0; }
.cd-summary { font-size:12px; line-height:1.6; color:var(--muted); margin:10px 0 0; }
.cd-summary strong { display:block; font-weight:500; color:#d5d5d5; margin-bottom:3px; }
.cd-notice { font-size:12px; line-height:1.6; margin:10px 0 0; color:#dfc395; }
.cd-notice[data-tone=conflict] { color:#e6b2b2; }
.cd-tabs { display:flex; flex-wrap:wrap; gap:3px; margin:0 14px; padding:4px; border:1px solid var(--line); border-radius:7px; background:#191919; }
.cd-tabs button { flex:1 1 100px; min-width:0; cursor:pointer; padding:8px 6px; border-radius:4px; font-size:12px; color:var(--muted); }
.cd-tabs button.active { background:#333; color:#f0f0f0; }
.cd-tabs button:focus-visible { outline:2px solid #999; }
.cd-body { padding:20px; }
.cd-back { display:none; margin:0 0 14px -8px; }
.cd-muted,.cd-loading { font-size:13px; color:var(--muted); line-height:1.7; }
.cd-loading { display:flex; gap:8px; align-items:center; }
.cd-excluded h3 { font-size:14px; font-weight:600; margin:0 0 10px; }
.cd-excluded p { font-size:13px; line-height:1.7; margin:0 0 16px; }
.cd-technical { font-size:12px; }
.cd-technical dl { margin:0; display:grid; gap:12px; }
.cd-technical dt { color:var(--muted); margin-bottom:3px; }
.cd-technical dd { margin:0; overflow-wrap:anywhere; }
.cd-json { margin:18px 0; }
.cd-technical details { margin-top:16px; padding-top:12px; border-top:1px solid var(--line); }
.cd-technical summary { cursor:pointer; }
.cd-technical article { margin-top:12px; line-height:1.6; }
.cd-technical article p { margin:3px 0; }
.cd-technical article small { color:var(--muted); overflow-wrap:anywhere; }
@media(max-width:959px){.cd-back{display:inline-flex}.cd-header{padding:16px}.cd-body{padding:16px}}
</style>
