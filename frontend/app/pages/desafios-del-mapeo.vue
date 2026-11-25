<script setup lang="ts">
useHead({ title: 'Desafíos del mapeo · Mapeo terminológico' })
const detail = ref('code')
const scenarios = [
  {id:'code',label:'Solo código',input:'Código CIE-10 de una afección',result:'El código permite explorar varios conceptos. El registro no aporta el subtipo para distinguirlos.'},
  {id:'a',label:'Con subtipo A',input:'Código CIE-10 + diagnóstico que especifica el subtipo A',result:'El diagnóstico aporta un dato para contrastar el candidato A con sus fuentes y descartar alternativas con otro subtipo.'},
  {id:'b',label:'Con subtipo B',input:'Código CIE-10 + diagnóstico que especifica el subtipo B',result:'Al cambiar el subtipo documentado, cambia el candidato que merece revisión. La elección depende de la información del registro.'}
]
const scenario = computed(()=>scenarios.find(item=>item.id===detail.value)!)
const concepts = [
  {id:'general',label:'Concepto general',description:'Conserva una descripción amplia de la afección.'},
  {id:'a',label:'Concepto con subtipo A',description:'Añade una característica clínica específica.'},
  {id:'b',label:'Concepto con subtipo B',description:'Representa otra variante de la misma afección.'}
]
</script>

<template>
  <article class="project-page">
    <header class="project-intro">
      <p class="project-eyebrow">DESAFÍOS DEL MAPEO</p>
      <h1>De una categoría<br /><span>a varias posibilidades clínicas.</span></h1>
      <p>Por qué las diferencias de detalle entre CIE-10 y SNOMED CT requieren contexto para distinguir candidatos.</p>
    </header>
    <div class="project-content">
      <section id="desafios" class="project-section challenge-section" aria-labelledby="desafios-title">
        <div class="section-heading"><div><p class="project-eyebrow">GRANULARIDAD Y AMBIGÜEDAD</p><h2 id="desafios-title">Un código puede abrir varias posibilidades.</h2></div></div>
        <p class="section-lead">La dificultad aparece al pasar de una categoría que agrupa diagnósticos a conceptos que distinguen características más específicas. El código de origen puede aportar menos detalle del necesario para elegir entre ellos.</p>
        <div class="challenge-grid">
          <div><span class="small-index">INFORMACIÓN DISPONIBLE</span><h3>El título no es toda la descripción clínica</h3><p>Los títulos CIE-10 son breves. Las inclusiones, exclusiones y reglas amplían su alcance, pero una categoría puede agrupar distintas localizaciones, subtipos o presentaciones. Recuperar ese contexto mejora su interpretación; el detalle individual depende de lo que se haya documentado sobre el paciente.</p></div>
          <div><span class="small-index">RELACIÓN 1:N</span><h3>Una categoría, varios candidatos</h3><p>Un código puede relacionarse con varios conceptos SNOMED CT de distinto alcance. Entre ellos puede haber conceptos generales y otros más específicos. Distinguirlos requiere comprobar qué características comparten con el registro y cuáles añaden, omiten o contradicen.</p></div>
        </div>

        <figure class="ambiguity-figure">
          <figcaption><div><span>EXPLORA LA RELACIÓN 1:N</span><strong>¿Qué cambia cuando hay más contexto?</strong></div><small>Esquema conceptual</small></figcaption>
          <div class="scenario-controls" role="group" aria-label="Contexto disponible para el ejemplo"><button v-for="item in scenarios" :key="item.id" type="button" :aria-pressed="detail===item.id" :class="{active:detail===item.id}" @click="detail=item.id">{{ item.label }}</button></div>
          <div class="ambiguity-flow">
            <div class="origin-node"><span class="system-label cie">CIE-10</span><strong>{{ scenario.input }}</strong><p>Una categoría de origen</p></div>
            <div class="branch-connector" aria-hidden="true"><span>1:N</span><svg viewBox="0 0 90 210" preserveAspectRatio="none"><path d="M0 105 H35 M35 35 V175 M35 35 H90 M35 105 H90 M35 175 H90" fill="none" stroke="currentColor" stroke-width="1.5" /></svg></div>
            <div class="concept-stack"><div class="concepts-label"><span class="system-label snomed">SNOMED CT</span><small>Posibles conceptos a contrastar</small></div><div v-for="concept in concepts" :key="concept.id" class="concept-option" :class="{highlighted:detail===concept.id,muted:detail!=='code'&&detail!==concept.id}"><UIcon :name="detail===concept.id?'i-lucide-focus':'i-lucide-circle'" /><div><strong>{{ concept.label }}</strong><p>{{ concept.description }}</p></div><span v-if="detail===concept.id" class="context-tag">Detalle documentado</span></div></div>
          </div>
          <p class="scenario-result" aria-live="polite">{{ scenario.result }}</p>
          <p class="figure-caption">La relación 1:N describe varias posibilidades de correspondencia; el grado de equivalencia se evalúa para cada candidato.</p>
        </figure>

        <div class="section-footer"><div class="project-sources"><span>Para profundizar</span><a class="source-link" href="https://docs.snomed.org/snomed-ct-practical-guides/snomed-ct-mapping-guide/developing-use-case-and-requirements/5.3.2-mapping-rules" target="_blank" rel="noopener noreferrer">Dirección, patrones y equivalencia <UIcon name="i-lucide-arrow-up-right" /></a><a class="source-link" href="https://www.who.int/standards/classifications/classification-of-diseases" target="_blank" rel="noopener noreferrer">OMS · Clasificación de enfermedades <UIcon name="i-lucide-arrow-up-right" /></a></div><UButton to="/" color="neutral" variant="outline" trailing-icon="i-lucide-arrow-right">Explorar la plataforma</UButton></div>
      </section>
      <nav class="project-page-navigation" aria-label="Volver al contexto del proyecto"><UButton to="/proyecto" color="neutral" variant="ghost" leading-icon="i-lucide-arrow-left">Por qué este proyecto</UButton></nav>
    </div>
  </article>
</template>

<style scoped src="../assets/css/project.css"></style>
