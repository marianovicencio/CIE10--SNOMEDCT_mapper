<script setup lang="ts">
import type { ExplanationState } from '~/types/explanation'
import { explanationHeading } from '~/types/explanation'
const props = defineProps<{ state?: ExplanationState, disabled: boolean, available: boolean }>()
defineEmits<{ generate: [], regenerate: [], sources: [refs: string[]] }>()
const isGenerated = computed(() => ['local_model', 'openai_model'].includes(props.state?.result?.generation_method || '') && Boolean(props.state?.result?.attributed_claims?.length))
const heading = computed(() => explanationHeading(props.state?.result))
const citedEvidence = computed(() => {
  if (!props.state?.result?.analysis) return (props.state?.result?.available_evidence ?? []).map(item => ({ ...item, paragraphs: [] as number[] }))
  return (props.state.result.analysis.quotes ?? []).map(quote => {
  const meta = props.state?.result?.evidence?.find(item => item.id === quote.evidence_id)
  const paragraphs = (props.state?.result?.attributed_claims ?? [])
    .flatMap((claim, index) => claim.evidence_refs.includes(quote.evidence_id) ? [index + 1] : [])
  return { id: quote.evidence_id, text: meta?.reading_text || quote.text,
    label: meta?.label || 'Fuente documental', source: meta?.source || '', paragraphs }
})
})
</script>
<template>
  <section class="ce-explanation" data-tour="explanation" aria-label="Explicación del candidato" aria-live="polite">
    <p v-if="state?.loading" class="ce-loading" role="status"><UIcon name="i-lucide-loader-circle" class="animate-spin" /> Preparando la explicación…</p>
    <template v-else-if="state?.result?.analysis && isGenerated">
      <h3>{{ heading }}</h3>
      <p v-if="state.result.recovery_context_selection" class="ce-evidence-note">Comparación acotada a los términos y al contexto SNOMED citado, generada tras los intentos con más contexto. No propone una selección automática.</p>
      <template v-if="state.result.attributed_claims?.length">
        <article v-for="(claim,index) in state.result.attributed_claims" :key="index" class="ce-claim">
          <p>{{ claim.text }}</p>
        </article>
      </template>
      <ul v-if="state.result.analysis.additional_detail_needed.length" class="ce-missing"><li v-for="detail in state.result.analysis.additional_detail_needed" :key="detail">{{ detail }}</li></ul>
      <div class="ce-actions">
        <UButton color="neutral" variant="outline" size="xs" @click="$emit('sources',state.result.analysis.quotes.map(q=>q.evidence_id))">Consultar fuentes</UButton>
        <UButton color="neutral" variant="ghost" size="xs" :disabled="disabled || !available" @click="$emit('regenerate')">Volver a generar</UButton>
      </div>
    </template>
    <template v-else>
      <p v-if="state?.error || state?.result" role="alert" class="ce-error">{{ state.error || state.result?.message || 'No se pudo completar la explicación. Puedes reintentarlo.' }}</p>
      <details v-if="state?.result?.errors?.length" class="ce-error-details"><summary>Detalle del fallo</summary><ul><li v-for="(error,index) in state.result.errors" :key="index">Intento {{ index + 1 }}: {{ error }}</li></ul></details>
      <p v-if="!state?.error && !state?.result">Revisa por qué este candidato podría corresponder al diagnóstico y qué información falta para decidir.</p>
      <UButton icon="i-lucide-message-square-text" color="neutral" variant="outline" :disabled="disabled || !available" @click="$emit('generate')">{{ state?.error || state?.result ? 'Reintentar explicación' : 'Explicar este candidato' }}</UButton>
      <p v-if="!available" class="ce-error">Vuelve a realizar la búsqueda para recuperar las versiones de la consulta.</p>
    </template>
      <details v-if="!state?.loading && citedEvidence.length" class="ce-evidence">
        <summary>{{ state?.result?.analysis ? 'Evidencia citada por el modelo' : 'Evidencia disponible para revisar' }} <span>{{ citedEvidence.length }}</span></summary>
        <p v-if="state?.result?.analysis" class="ce-evidence-note">Fragmentos asociados a las citas de la explicación. Las citas permiten revisar su fundamento; no muestran el razonamiento interno del modelo.</p>
        <p v-else class="ce-evidence-note">Fuentes enviadas en el último intento. Son información documental, no una explicación generada.</p>
        <article v-for="item in citedEvidence" :key="item.id" class="ce-evidence-item">
          <header><strong>{{ item.label }}</strong><small v-if="(state?.result?.attributed_claims?.length ?? 0) > 1">Párrafo{{ item.paragraphs.length > 1 ? 's' : '' }} {{ item.paragraphs.join(', ') }}</small></header>
          <blockquote>{{ item.text }}</blockquote>
          <small>{{ item.source }}</small>
        </article>
      </details>
  </section>
</template>
<style scoped>
.ce-explanation { font-size:13px; line-height:1.7; }
.ce-explanation h3 { margin:0 0 12px; font-size:14px; font-weight:600; }
.ce-explanation p { margin:0 0 14px; }
.ce-loading { display:flex; align-items:center; gap:8px; color:var(--muted); }
.ce-error { color:#dfc395; }
.ce-missing { list-style:disc; padding-left:20px; margin:12px 0; }
.ce-claim { margin-bottom:16px; }
.ce-actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:18px; }
.ce-evidence { margin-top:18px; border-top:1px solid var(--line); padding-top:14px; }
.ce-evidence summary { cursor:pointer; font-weight:500; }
.ce-evidence summary span { color:var(--muted); margin-left:6px; font-size:11px; }
.ce-evidence-note { color:var(--muted); font-size:12px; margin-top:12px !important; }
.ce-evidence-item { padding:12px 0; border-bottom:1px solid var(--line); min-width:0; }
.ce-evidence-item header { display:flex; flex-wrap:wrap; gap:6px 12px; justify-content:space-between; }
.ce-evidence-item strong { font-size:12px; font-weight:500; }
.ce-evidence-item blockquote { margin:8px 0; padding-left:12px; border-left:2px solid #555; white-space:pre-line; overflow-wrap:anywhere; }
.ce-evidence-item small { color:var(--muted); font-size:11px; overflow-wrap:anywhere; }
.ce-error-details { color:var(--muted); margin:0 0 16px; }
.ce-error-details summary { cursor:pointer; }
</style>
