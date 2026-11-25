<script setup lang="ts">
import type { ContextReview } from '~/types/context-review'
const props = defineProps<{ review?: ContextReview }>()
const comparison = computed(() => props.review?.comparison)
const mainDimensions = computed(() => comparison.value?.dimensions.filter(item => item.status !== 'context') ?? [])
const supportingDimensions = computed(() => comparison.value?.dimensions.filter(item => item.status === 'context') ?? [])
const scopeLabels: Record<string, string> = {
  asserted: 'Texto afirmado', negated: 'Mención negada', hypothetical: 'Hipótesis',
  uncertain: 'Información incierta', historical: 'Antecedente', other_subject: 'Mención a otra persona'
}
</script>
<template>
  <section v-if="review" class="cc-comparison" aria-label="Comparación del alcance de los conceptos">
    <template v-if="comparison">
      <header class="cc-summary" :data-tone="comparison.summary.status">
        <h3>{{ comparison.summary.title }}</h3>
        <p>{{ comparison.summary.text }}</p>
      </header>
      <div class="cc-dimensions">
        <ComparisonDimension v-for="dimension in mainDimensions" :key="dimension.id" :dimension="dimension" :sources="comparison.sources" />
      </div>
      <details v-if="supportingDimensions.length" class="cc-support">
        <summary>Contexto de codificación y atributos <span>{{ supportingDimensions.length }}</span></summary>
        <div class="cc-dimensions"><ComparisonDimension v-for="dimension in supportingDimensions" :key="dimension.id" :dimension="dimension" :sources="comparison.sources" /></div>
      </details>
      <section v-if="comparison.input" class="cc-input" aria-label="Contexto del diagnóstico escrito">
        <header><h4>Diagnóstico aportado</h4><span class="cc-status" :data-status="comparison.input.scope === 'asserted' ? 'context' : 'not_explicit'">{{ scopeLabels[comparison.input.scope] || 'Contexto por revisar' }}</span></header>
        <p>{{ comparison.input.text }}</p>
        <small>Se muestra por separado del alcance oficial del código.</small>
      </section>
      <div v-if="review.constraint?.additional_detail_needed?.length" class="cc-missing"><h4>Detalles por aclarar</h4><ul><li v-for="item in review.constraint.additional_detail_needed" :key="item">{{ item }}</li></ul></div>
    </template>
    <template v-else>
      <h3>{{ review.constraint ? 'Restricción documentada' : 'Comparación no disponible' }}</h3>
      <p>{{ review.constraint?.justification || 'Repite la consulta para recuperar la comparación por dimensiones y su respaldo documental.' }}</p>
    </template>
  </section>
</template>
<style scoped>
.cc-comparison { min-width:0; font-size:13px; line-height:1.65; }
.cc-summary { margin-bottom:20px; padding-bottom:18px; border-bottom:1px solid var(--line); }
.cc-summary h3,.cc-comparison h3 { font-size:15px; line-height:1.45; font-weight:600; margin:0 0 8px; }
.cc-summary > p:last-child { color:var(--muted); margin:0; }
.cc-summary[data-tone=conflict] h3 { color:#e6b2b2; }
.cc-dimensions { display:grid; gap:14px; }
.cc-status { font-size:10px; padding:3px 7px; border:1px solid #393939; border-radius:4px; color:#c9c9c9; background:#1c1c1c; }
.cc-input header { display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px; }
.cc-input h4,.cc-missing h4 { margin:0; font-size:13px; font-weight:600; }
.cc-input small { color:var(--muted); font-size:11px; }
.cc-support { margin-top:18px; }
.cc-support > summary { cursor:pointer; color:var(--muted); font-size:12px; padding:12px 0; }
.cc-support > summary span { margin-left:6px; font-size:10px; }
.cc-input { margin-top:20px; padding-top:18px; border-top:1px solid var(--line); }
.cc-input p { white-space:pre-line; overflow-wrap:anywhere; margin:10px 0 6px; }
.cc-missing { margin-top:20px; color:#dfc395; }
.cc-missing ul { list-style:disc; padding-left:20px; margin:8px 0 0; }

</style>
