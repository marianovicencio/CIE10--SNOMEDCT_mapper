<script setup lang="ts">
useHead({ title: 'Por qué este proyecto · Mapeo terminológico' })
</script>

<template>
  <article class="project-page">
    <header class="project-intro">
      <p class="project-eyebrow">POR QUÉ ESTE PROYECTO</p>
      <h1>Conectar lo registrado<br /><span>con la continuidad del cuidado.</span></h1>
      <p>Explorar la relación entre los diagnósticos codificados en CIE-10 y una terminología capaz de representar el detalle clínico: SNOMED CT.</p>
    </header>
    <div class="project-content">
      <section id="continuidad" class="project-section" aria-labelledby="continuidad-title">
        <div class="section-heading"><div><p class="project-eyebrow">CONTEXTO Y PROPÓSITO</p><h2 id="continuidad-title">¿Por qué este proyecto es necesario hoy?</h2></div></div>
        <p class="section-lead">La información registrada en CIE-10 sigue siendo parte de la historia clínica. Vincularla con SNOMED CT permite estudiar cómo aprovecharla cuando la atención continúa en sistemas que utilizan una terminología de mayor detalle.</p>

        <div class="purpose-grid">
          <div class="purpose-copy">
            <h3>Una necesidad en el contexto chileno</h3>
            <p>La arquitectura de interoperabilidad de MINSAL busca que la información clínica esté disponible a lo largo de la atención, aunque se haya registrado en distintos establecimientos. En ese marco, contempla SNOMED CT como terminología de referencia para los registros clínicos electrónicos, según los casos de uso.</p>
            <p>Su capacidad para representar conceptos, descripciones y relaciones clínicas favorece un registro más preciso y el intercambio de significado entre sistemas. También permite vincular la información con herramientas de consulta y apoyo a decisiones clínicas.</p>
            <a class="source-link" href="https://interoperabilidad.minsal.cl/docs/especificacion-de-la-arquitectura/estandares-perfiles.html" target="_blank" rel="noopener noreferrer">MINSAL · Estándares y perfiles <UIcon name="i-lucide-arrow-up-right" /></a>
          </div>
          <div class="standards-comparison" aria-label="Propósitos de CIE-10 y SNOMED CT">
            <div class="standard-card"><span class="system-label cie">CIE-10</span><h3>Clasificar y agrupar</h3><p>Organiza enfermedades y otros problemas de salud para el registro y la comparación de datos de morbilidad y mortalidad.</p><span class="standard-foot">Una perspectiva estadística y epidemiológica</span></div>
            <div class="standard-card"><span class="system-label snomed">SNOMED CT</span><h3>Representar el detalle clínico</h3><p>Expresa afecciones, hallazgos y otros conceptos del proceso asistencial, con descripciones y relaciones entre ellos.</p><span class="standard-foot">Una base semántica para el registro clínico</span></div>
          </div>
        </div>

        <figure class="continuity-figure">
          <figcaption><span>EL MISMO PACIENTE, A LO LARGO DEL TIEMPO</span><strong>Que el cambio de sistema conserve el significado.</strong></figcaption>
          <div class="continuity-flow">
            <div class="continuity-node"><UIcon name="i-lucide-file-clock" /><small>Información ya registrada</small><strong>Historia codificada en CIE-10</strong><p>Diagnósticos y contexto disponibles del registro de origen.</p></div>
            <div class="continuity-bridge"><span class="bridge-line" /><span>Interpretar y vincular</span><UIcon name="i-lucide-arrow-right" /><span class="bridge-line" /></div>
            <div class="continuity-node"><UIcon name="i-lucide-heart-pulse" /><small>Nuevas atenciones</small><strong>Registro clínico con SNOMED CT</strong><p>Conceptos que puedan compartirse, consultarse y relacionarse.</p></div>
          </div>
          <p class="figure-caption">La dirección CIE-10 → SNOMED CT parte de los datos existentes para estudiar su reutilización en el entorno clínico receptor.</p>
        </figure>

        <div class="direction-note"><UIcon name="i-lucide-arrow-left-right" /><div><h3>¿Por qué recorrer una dirección que parece contraintuitiva?</h3><p>Agrupar conceptos clínicos detallados en una categoría estadística reduce información. Partir de esa categoría para llegar a SNOMED CT exige distinguir qué detalle conserva el registro. Por eso investigamos esta dirección: la información histórica ya existe en CIE-10 y queremos conectarla con el nuevo entorno de atención.</p><p>El <a href="https://www.snomed.org/maps" target="_blank" rel="noopener noreferrer" class="inline-source">mapa oficial SNOMED CT → CIE-10</a> tiene un propósito y una dirección definidos. Resolver el recorrido inverso requiere evaluar sus propias correspondencias y condiciones.</p><a class="source-link" href="https://docs.snomed.org/snomed-ct-practical-guides/snomed-ct-data-analytics-guide/5-preparing-data-for-analytics/5.2-mapping-other-code-systems-to-snomed-ct" target="_blank" rel="noopener noreferrer">SNOMED International · Mapeo desde otros sistemas <UIcon name="i-lucide-arrow-up-right" /></a></div></div>
      </section>
      <nav class="project-page-navigation" aria-label="Continuar en Proyecto"><UButton to="/desafios-del-mapeo" color="neutral" variant="outline" trailing-icon="i-lucide-arrow-right">Desafíos del mapeo</UButton></nav>
    </div>
  </article>
</template>

<style scoped src="../assets/css/project.css"></style>
