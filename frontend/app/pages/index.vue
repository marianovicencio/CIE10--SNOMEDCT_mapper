<script setup lang="ts">
import type { Candidate } from '~/types/consultation'
import { candidateNotice, documentTitle } from '~/types/consultation'
const {
  code,diagnostic,suggestions,suggestionsLoading,suggestionsUnavailable,enteredTitle,
  cleanCode,restrictCodeInput,explanationProvider,externalConsent,doc,result,terms,
  selected,focusId,busy,contextLoading,contextError,contextCompleted,progressLabel,
  message,pendingCodeChange,submittedCode,explanationContext,explanations,
  explanationBusy,loadingMore,documentMessage,search,explain,reviewCurrentCandidates,more
}=useConsultation()
const advancedOpen=ref(false)
const {data:catalog,execute:loadCatalog}=useFetch<{concepts:number,aliases:number}>('/api/catalogo',{immediate:false,retry:0})
watch(advancedOpen,open=>{if(open&&!catalog.value)void loadCatalog()})
const validCode=computed(()=>/^[A-Z][0-9]{2}(?:\.[0-9]{1,2})?$/.test(code.value))
const needsConsent=computed(()=>explanationProvider.value==='openai'&&!externalConsent.value)
async function chooseCandidate(candidate:Candidate){
  focusId.value=candidate.id
  await nextTick()
  if(window.matchMedia('(max-width: 959px)').matches){
    const element=document.getElementById('candidate-detail')
    element?.focus({preventScroll:true});element?.scrollIntoView({block:'start'})
  }
}
async function returnToCandidates(){
  const previous=focusId.value
  focusId.value=null
  await nextTick()
  document.getElementById('candidate-choice-'+previous)?.focus({preventScroll:true})
  if(window.matchMedia('(max-width: 959px)').matches)document.getElementById('candidate-options')?.scrollIntoView({block:'start'})
}
</script>

<template>
  <div class="cc-page">
    <header class="cc-intro" data-tour="intro"><h1>CIE-10 <span>→</span> SNOMED CT</h1><p>Busca y compara conceptos a partir de un código CIE-10.</p></header>
    <main class="cc-workspace">
      <form class="cc-query" aria-label="Consulta de códigos" @submit.prevent="search()">
        <div class="cc-fields">
          <UFormField label="Código CIE-10" required>
            <div data-tour="code" @input.capture="restrictCodeInput">
              <UInputMenu :model-value="code" @update:model-value="code=cleanCode(String($event??''))" mode="autocomplete" :items="suggestions" value-key="code" label-key="code" description-key="title" ignore-filter open-on-focus :loading="suggestionsLoading" placeholder="Ej. C76.4" icon="i-lucide-search" size="lg" class="w-full code-input" autocomplete="off" autocapitalize="characters" :spellcheck="false" :disabled="busy" :ui="{content:'max-h-56',itemDescription:'whitespace-normal leading-snug',itemLabel:'font-semibold tabular-nums'}">
                <template #empty>{{ !code?'Escribe la primera letra del código.':suggestionsLoading?'Buscando códigos…':suggestionsUnavailable?'Sugerencias no disponibles.':'Sin códigos con este prefijo.' }}</template>
              </UInputMenu>
            </div>
            <p v-if="enteredTitle" class="cc-code-title">{{ enteredTitle }}</p>
          </UFormField>
          <UFormField label="Diagnóstico escrito" hint="Opcional"><UTextarea data-tour="diagnostic" v-model="diagnostic" placeholder="Añade detalles del diagnóstico…" :rows="2" :maxlength="4000" class="w-full" :disabled="busy" /></UFormField>
        </div>
        <div class="cc-query-actions">
          <button type="button" class="cc-advanced-toggle" data-tour="advanced" :aria-expanded="advancedOpen" aria-controls="consultation-options" @click="advancedOpen=!advancedOpen"><UIcon name="i-lucide-sliders-horizontal" /> Opciones avanzadas <UIcon :name="advancedOpen?'i-lucide-chevron-up':'i-lucide-chevron-down'" /></button>
          <UButton type="submit" class="search-submit cc-submit" data-tour="search" size="lg" :loading="busy" :disabled="busy||!validCode" trailing-icon="i-lucide-arrow-right">{{ busy?'Buscando…':'Buscar candidatos SNOMED CT' }}</UButton>
        </div>
        <section v-if="advancedOpen" id="consultation-options" class="cc-advanced" aria-label="Opciones avanzadas">
          <UFormField label="Generador de explicaciones"><USelect v-model="explanationProvider" :items="[{label:'Modelo local',value:'local'},{label:'API externa configurada',value:'openai'}]" class="w-full" :disabled="busy||explanationBusy" /></UFormField>
          <p>Se utiliza solo al pedir una explicación; no cambia la búsqueda de candidatos.</p>
          <template v-if="explanationProvider==='openai'"><p>La conexión externa actual utiliza OpenAI y tu saldo de API. El proveedor se identifica aquí antes de autorizar cualquier envío.</p><UCheckbox v-model="externalConsent" label="Autorizo enviar a la conexión externa indicada el contexto seleccionado y el diagnóstico escrito, si lo incluí." /></template>
          <small v-if="catalog">Catálogo: {{ catalog.concepts.toLocaleString('es-CL') }} conceptos · {{ catalog.aliases.toLocaleString('es-CL') }} términos en español.</small>
        </section>
      </form>

      <p v-if="pendingCodeChange" class="cc-pending" role="status">Modificaste la consulta. Busca de nuevo para actualizar los resultados de {{ submittedCode }}.</p>
      <UAlert v-if="message" color="warning" variant="soft" icon="i-lucide-circle-alert" title="No se pudo completar la búsqueda" :description="message" />

      <section v-if="doc" class="cc-code-summary" data-tour="documentation" aria-label="Código CIE-10 consultado">
        <div class="cc-code-heading"><span class="cc-code">{{ doc.code }}</span><h2>{{ documentTitle(doc) }}</h2></div>
        <details class="cc-document"><summary>Consultar información CIE-10</summary><div class="cc-document-body"><CodeDocumentation :document="doc" :loading="loadingMore" :error="documentMessage" @more="more" /></div></details>
      </section>

      <div v-if="busy" class="cc-loading" role="status"><UIcon name="i-lucide-loader-circle" class="animate-spin" /><div><strong>{{ progressLabel }}</strong></div></div>

      <template v-else-if="terms.length&&doc&&result">
        <div v-if="contextError" class="cc-review-error" role="alert"><div><strong>La comparación no se completó</strong><p>{{ contextError }} Los candidatos siguen disponibles.</p></div><UButton color="neutral" variant="outline" size="xs" :loading="contextLoading" :disabled="explanationBusy||pendingCodeChange" @click="reviewCurrentCandidates()">Reintentar comparación</UButton></div>
        <div v-else-if="contextLoading" class="cc-comparison-progress" role="status"><UIcon name="i-lucide-loader-circle" class="animate-spin" /> Revisando coincidencias y diferencias…</div>
        <div class="cc-results" :class="{'cc-has-selection':Boolean(selected)}">
          <section id="candidate-options" data-tour="candidates" class="cc-options" aria-label="Candidatos SNOMED CT">
            <header><h2>Candidatos SNOMED CT</h2><span>{{ terms.length }}</span></header>
            <ul>
              <li v-for="candidate in terms" :key="candidate.id">
                <button :id="'candidate-choice-'+candidate.id" type="button" class="cc-choice" :class="{'cc-selected':focusId===candidate.id}" :aria-pressed="focusId===candidate.id" aria-controls="candidate-detail" @click="chooseCandidate(candidate)">
                  <span class="cc-position" aria-hidden="true">{{ String(candidate.rank).padStart(2,'0') }}</span><span class="cc-choice-content"><strong>{{ candidate.term }}</strong><small v-if="candidateNotice(candidate)" :data-tone="candidateNotice(candidate)?.tone">{{ candidateNotice(candidate)?.label }}</small></span><UIcon name="i-lucide-chevron-right" class="cc-choice-arrow" />
                </button>
              </li>
            </ul>
          </section>
          <div class="cc-detail-panel">
            <CandidateDetail v-if="selected" :candidate="selected" :document="doc" :result="result" :state="explanations[selected.id]" :disabled="explanationBusy||contextLoading||pendingCodeChange||needsConsent" :available="Boolean(explanationContext)" :context-loading="contextLoading" :context-error="contextError" :needs-consent="needsConsent" :other-explanation-running="explanationBusy&&!explanations[selected.id]?.loading" @generate="explain(selected)" @regenerate="explain(selected,true)" @back="returnToCandidates" />
            <div v-else class="cc-detail-placeholder"><UIcon name="i-lucide-panel-right" /><h2>Selecciona un candidato</h2><p>Consulta su comparación, explicación y fuentes.</p></div>
          </div>
        </div>
      </template>
      <section v-else-if="!busy" class="cc-empty" aria-live="polite"><UIcon name="i-lucide-search" /><h2>{{ doc?'No hay candidatos disponibles':'Los candidatos aparecerán aquí' }}</h2><p>{{ doc?'Revisa el código o intenta nuevamente la búsqueda.':'Introduce un código para comenzar.' }}</p></section>
    </main>
  </div>
</template>

<style scoped>
.cc-page { min-width:0; }
.cc-intro { padding:24px 26px 20px; border-bottom:1px solid var(--line); }
.cc-intro h1 { margin:0 0 7px; font-size:25px; font-weight:650; letter-spacing:-.035em; }
.cc-intro h1 span { color:var(--muted); margin-inline:3px; }
.cc-intro p { margin:0; font-size:13px; color:var(--muted); line-height:1.6; }
.cc-workspace { padding:22px 26px 26px; display:grid; gap:20px; min-width:0; }
.cc-query { padding:20px; border:1px solid var(--line); border-radius:10px; background:var(--panel); min-width:0; }
.cc-fields { display:grid; grid-template-columns:minmax(200px,.85fr) minmax(0,1.5fr); gap:24px; align-items:start; }
.cc-code-title { color:var(--muted); font-size:12px; line-height:1.5; margin:7px 0 0; }
.cc-query-actions { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:14px; margin-top:18px; }
.cc-advanced-toggle { display:flex; align-items:center; gap:7px; font-size:12px; color:var(--muted); cursor:pointer; padding:5px 0; }
.cc-submit { min-width:245px; justify-content:center; }
.cc-advanced { display:grid; gap:10px; border-top:1px solid var(--line); padding-top:18px; margin-top:18px; max-width:650px; }
.cc-advanced p,.cc-advanced small { color:var(--muted); font-size:12px; line-height:1.6; margin:0; }
.cc-pending { color:#dfc395; font-size:12px; line-height:1.6; margin:0; }
.cc-code-summary { border-bottom:1px solid var(--line); padding-bottom:16px; min-width:0; }
.cc-code-heading { display:flex; gap:12px; align-items:baseline; }
.cc-code-heading h2 { font-size:14px; font-weight:550; line-height:1.6; overflow-wrap:anywhere; }
.cc-code { flex:none; color:#dedede; background:#202020; border:1px solid #353535; padding:4px 7px; border-radius:5px; font:600 12px ui-monospace,monospace; }
.cc-document { margin-top:10px; font-size:12px; }
.cc-document > summary { cursor:pointer; color:var(--muted); width:fit-content; }
.cc-document-body { padding:18px 0 4px; }
.cc-results { display:grid; grid-template-columns:minmax(240px,.85fr) minmax(0,1.5fr); align-items:start; gap:18px; min-width:0; }
.cc-options,.cc-detail-panel { min-width:0; border:1px solid var(--line); border-radius:10px; background:var(--panel); }
.cc-options { scroll-margin-top:65px; overflow:hidden; }
.cc-options > header { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:17px 16px; border-bottom:1px solid var(--line); }
.cc-options > header h2 { font-size:14px; }
.cc-options > header > span { color:var(--muted); font-size:12px; }
.cc-options ul { list-style:none; margin:0; padding:0; }
.cc-options li+li { border-top:1px solid var(--line); }
.cc-choice { width:100%; display:flex; align-items:flex-start; gap:10px; padding:17px 15px; text-align:left; cursor:pointer; background:transparent; }
.cc-choice:hover { background:#1b1b1b; }
.cc-choice.cc-selected { background:#232323; box-shadow:inset 2px 0 #ddd; }
.cc-choice:focus-visible,.cc-advanced-toggle:focus-visible { outline:2px solid #999; outline-offset:-2px; }
.cc-position { flex:none; font:11px ui-monospace,monospace; color:var(--muted); padding-top:3px; }
.cc-choice-content { flex:1; min-width:0; }
.cc-choice-content strong { display:block; font-size:13px; font-weight:550; line-height:1.6; overflow-wrap:anywhere; }
.cc-choice-content small { display:block; margin-top:5px; color:#dfc395; font-size:11px; line-height:1.5; }
.cc-choice-content small[data-tone=conflict] { color:#e6b2b2; }
.cc-choice-arrow { flex:none; color:var(--muted); margin-top:3px; }
.cc-detail-panel { scroll-margin-top:65px; }
.cc-detail-placeholder { min-height:300px; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:28px; text-align:center; }
.cc-detail-placeholder > span { color:#737373; font-size:23px; margin-bottom:14px; }
.cc-detail-placeholder h2 { font-size:14px; margin:0 0 8px; }
.cc-detail-placeholder p { color:var(--muted); font-size:12px; line-height:1.6; margin:0; }
.cc-empty { min-height:220px; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:30px; text-align:center; }
.cc-empty > span { color:#737373; font-size:26px; margin-bottom:16px; }
.cc-empty h2 { font-size:15px; margin:0 0 8px; }
.cc-empty p { color:var(--muted); margin:0; font-size:13px; }
.cc-loading { display:flex; align-items:center; justify-content:center; gap:14px; min-height:220px; padding:25px; color:var(--muted); }
.cc-loading > span { flex:none; font-size:21px; }
.cc-loading strong { color:#dedede; font-size:13px; font-weight:500; }
.cc-loading p { font-size:12px; margin:5px 0 0; }
.cc-review-error { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; padding:13px 15px; border:1px solid #53432a; border-radius:8px; font-size:12px; color:#dfc395; }
.cc-review-error p { margin:4px 0 0; line-height:1.6; }
.cc-comparison-progress { display:flex; gap:8px; align-items:center; color:var(--muted); font-size:12px; }
@media(max-width:959px){.cc-results{grid-template-columns:minmax(0,1fr)}.cc-results.cc-has-selection .cc-options{display:none}.cc-results:not(.cc-has-selection) .cc-detail-panel{display:none}.cc-intro{padding:20px}.cc-workspace{padding:18px}.cc-fields{grid-template-columns:minmax(0,1fr);gap:16px}}
@media(max-width:520px){.cc-intro{padding:18px 14px}.cc-intro h1{font-size:23px}.cc-workspace{padding:14px;gap:16px}.cc-query{padding:15px}.cc-submit{min-width:0;width:100%}.cc-code-heading{align-items:flex-start}.cc-code-heading h2{font-size:13px}.cc-query-actions{margin-top:16px}.cc-loading{justify-content:flex-start;padding:16px}}
</style>
