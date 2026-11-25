<script setup lang="ts">
const route = useRoute()
const guidedTour = useTemplateRef('guidedTour')
function prepareTour() { sidebarCollapsed.value = false; mobileMenuOpen.value = false }
const repositoryUrl = useRuntimeConfig().public.repositoryUrl.trim()
const sidebarCollapsed = ref(false)
const mobileMenuOpen = ref(false)
const cieEdition = useState('cie-edition', () => 'OPS/OMS CIE-10 2018')
const snomedRelease = useState('snomed-release', () => '20261110')
const formattedRelease = computed(() => snomedRelease.value.replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3'))
const navigationGroups = [
  {
    id: 'consulta',
    label: 'Consulta',
    items: [{ to: '/', label: 'Consulta de códigos', icon: 'i-lucide-arrow-left-right' }]
  },
  {
    id: 'proyecto',
    label: 'Proyecto',
    items: [
      { to: '/proyecto', label: 'Por qué este proyecto', icon: 'i-lucide-info' },
      { to: '/desafios-del-mapeo', label: 'Desafíos del mapeo', icon: 'i-lucide-git-fork' }
    ]
  },
  {
    id: 'documentacion',
    label: 'Documentación técnica',
    items: [
      { to: '/preprocesamiento', label: 'Preprocesamiento', icon: 'i-lucide-files' },
      { to: '/flujo-de-consulta', label: 'Flujo de consulta', icon: 'i-lucide-workflow' },
      { to: '/busqueda-de-candidatos', label: 'Búsqueda de candidatos', icon: 'i-lucide-search' },
      { to: '/modelos-y-explicaciones', label: 'Modelos y explicaciones', icon: 'i-lucide-message-square-text' }
    ]
  }
]
const navigation = navigationGroups.flatMap(group => group.items)
const activePage = computed(() => navigation.find(item => item.to === route.path) ?? navigation[0]!)
watch(() => route.path, () => { mobileMenuOpen.value = false })
</script>

<template>
  <div class="shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }" @keydown.esc="mobileMenuOpen = false">
    <button v-if="mobileMenuOpen" type="button" class="mobile-backdrop" aria-label="Cerrar navegación" @click="mobileMenuOpen = false" />
    <aside id="app-sidebar" class="app-sidebar" :class="{ 'mobile-open': mobileMenuOpen }">
      <div class="sidebar-brand">
        <span class="brand-icon" aria-hidden="true"><UIcon name="i-lucide-link-2" /></span>
        <div class="sidebar-label sidebar-title">
          <strong>Mapeo terminológico</strong>
          <span>CIE-10 <span class="brand-arrow">→</span> SNOMED CT</span>
        </div>
        <UButton class="mobile-close" icon="i-lucide-x" color="neutral" variant="ghost" aria-label="Cerrar navegación" @click="mobileMenuOpen = false" />
      </div>
      <nav data-tour="navigation" aria-label="Navegación principal">
        <div v-for="group in navigationGroups" :key="group.id" class="nav-group" role="group" :aria-labelledby="'nav-' + group.id">
          <p :id="'nav-' + group.id" class="nav-group-title">{{ group.label }}</p>
          <UButton
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            :icon="item.icon"
            color="neutral"
            :variant="route.path === item.to ? 'soft' : 'ghost'"
            block
            :aria-current="route.path === item.to ? 'page' : undefined"
            :aria-label="item.label"
            :title="item.label"
            class="nav-item"
            :class="{ 'nav-current': route.path === item.to }"
            @click="mobileMenuOpen = false"
          >
            <span class="sidebar-label">{{ item.label }}</span>
          </UButton>
        </div>
      </nav>
      <div class="sidebar-bottom">
        <UButton
          :href="repositoryUrl || undefined"
          :disabled="!repositoryUrl"
          :target="repositoryUrl ? '_blank' : undefined"
          rel="noopener noreferrer"
          icon="i-lucide-github"
          color="neutral"
          variant="outline"
          block
          class="repository-link"
          data-tour="repository"
          aria-label="GitHub"
          :title="repositoryUrl ? 'Abrir repositorio en GitHub' : 'URL del repositorio pendiente'"
        >
          <span class="sidebar-label">GitHub</span>
        </UButton>
        <section data-tour="versions" class="versions" aria-label="Versiones de los sistemas de códigos">
          <dl>
            <div><dt>CIE-10</dt><dd>{{ cieEdition.replace(/^OPS\/OMS CIE-10 /, 'OPS/OMS ') }}</dd></div>
            <div><dt>SNOMED CT</dt><dd>Español · {{ formattedRelease }}</dd></div>
          </dl>
        </section>
      </div>
    </aside>

    <GuidedTour ref="guidedTour" @start="prepareTour" @sidebar="mobileMenuOpen=$event" />
    <div class="app-main">
      <header class="topbar">
        <UButton class="desktop-toggle" icon="i-lucide-panel-left" color="neutral" variant="ghost" aria-label="Barra lateral" :title="sidebarCollapsed ? 'Expandir barra lateral' : 'Comprimir barra lateral'" aria-controls="app-sidebar" :aria-expanded="!sidebarCollapsed" @click="sidebarCollapsed = !sidebarCollapsed" />
        <UButton class="mobile-toggle" icon="i-lucide-panel-left" color="neutral" variant="ghost" aria-label="Barra lateral" aria-controls="app-sidebar" :aria-expanded="mobileMenuOpen" @click="mobileMenuOpen = !mobileMenuOpen" />
        <div class="breadcrumb"><UIcon :name="activePage.icon" /> {{ activePage.label }}</div>
        <div class="topbar-help"><UButton data-tour="restart" icon="i-lucide-circle-help" color="neutral" variant="ghost" size="sm" aria-label="Abrir tutorial guiado" title="Tutorial guiado" @click="guidedTour?.start()"><span class="tour-button-label">Tutorial</span></UButton><span class="local-tag"><span /> Entorno local</span></div>
      </header>

      <main class="dashboard-frame">
        <div class="dashboard">
          <slot />
        </div>
      </main>
    </div>
  </div>
</template>
