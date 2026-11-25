<script setup lang="ts">
import type { ScopeComparison, ComparisonStatus, ComparisonSource } from '~/types/context-review'
const props = defineProps<{ dimension: ScopeComparison['dimensions'][number], sources: ComparisonSource[] }>()
const visibleSources = computed(() => props.sources.filter(source => props.dimension.evidence_refs.includes(source.id)))
const statuses: Record<ComparisonStatus, string> = {
  same_wording: 'Coincidencia literal', supported_by_hierarchy: 'Respaldo jerárquico',
  candidate_narrower: 'Más específico', candidate_broader: 'Más amplio', candidate_detail: 'Detalle adicional',
  not_explicit: 'Por comprobar', different_wording: 'Formulación distinta', conflict: 'Contradicción verificada', context: 'Contexto de codificación'
}
</script>
<template>
  <article class="cc-dimension">
    <header class="cc-dimension-heading"><h4>{{ dimension.label }}</h4><span class="cc-status" :data-status="dimension.status">{{ statuses[dimension.status] }}</span></header>
    <dl class="cc-values">
      <div><dt>CIE-10</dt><dd>{{ dimension.cie.text }}</dd></div>
      <div><dt>SNOMED CT</dt><dd>{{ dimension.candidate.text }}<small v-if="dimension.candidate.detail">{{ dimension.candidate.detail }}</small></dd></div>
    </dl>
    <p class="cc-reading">{{ dimension.reading }}</p>
    <details v-if="visibleSources.length" class="cc-evidence">
      <summary>Ver respaldo documental</summary>
      <article v-for="source in visibleSources" :key="source.id" class="cc-source">
        <strong>{{ source.label }}</strong><blockquote>{{ source.text }}</blockquote><small>{{ source.provenance }}</small>
      </article>
    </details>
  </article>
</template>
<style scoped>
.cc-dimension { min-width:0; padding:16px; border:1px solid var(--line); border-radius:8px; font-size:13px; line-height:1.65; }
.cc-dimension-heading { display:flex; align-items:baseline; justify-content:space-between; flex-wrap:wrap; gap:8px 12px; }
.cc-dimension h4 { font-size:13px; line-height:1.5; font-weight:600; margin:0; }
.cc-status { flex-shrink:0; font-size:10px; line-height:1.5; padding:3px 7px; border:1px solid #393939; border-radius:4px; color:#c9c9c9; background:#1c1c1c; }
.cc-status[data-status=supported_by_hierarchy],.cc-status[data-status=same_wording] { color:#d5e0d6; border-color:#344237; background:#18201a; }
.cc-status[data-status=not_explicit],.cc-status[data-status=candidate_detail],.cc-status[data-status=candidate_narrower],.cc-status[data-status=candidate_broader] { color:#dfc395; border-color:#4b402e; background:#241e15; }
.cc-status[data-status=conflict] { color:#e6b2b2; border-color:#593838; background:#291b1b; }
.cc-values { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; margin:16px 0 14px; }
.cc-values > div { min-width:0; }
.cc-values dt { color:var(--muted); font-size:10px; letter-spacing:.04em; margin-bottom:6px; }
.cc-values dd { margin:0; overflow-wrap:anywhere; }
.cc-values small { display:block; color:var(--muted); font-size:11px; margin-top:6px; }
.cc-reading { margin:0; color:#bdbdbd; font-size:12px; }
.cc-evidence { margin-top:12px; padding-top:10px; border-top:1px solid var(--line); font-size:12px; }
.cc-evidence summary { cursor:pointer; color:var(--muted); }
.cc-source { margin-top:14px; }
.cc-source strong { display:block; font-size:11px; font-weight:500; }
.cc-source blockquote { margin:7px 0; padding-left:10px; border-left:2px solid #484848; white-space:pre-line; overflow-wrap:anywhere; }
.cc-source small { color:var(--muted); font-size:11px; overflow-wrap:anywhere; }
@media(max-width:640px) { .cc-values { grid-template-columns:minmax(0,1fr); gap:14px; } .cc-dimension { padding:13px; } }
</style>
