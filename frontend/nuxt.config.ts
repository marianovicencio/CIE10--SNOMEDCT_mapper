export default defineNuxtConfig({
  modules: ['@nuxt/ui'],
  css: ['~/assets/css/main.css'],
  ui: { fonts: false },
  icon: { clientBundle: { scan: true, icons: ["lucide:file-text", "lucide:scan-text", "lucide:list-tree", "lucide:database", "lucide:search", "lucide:files", "lucide:list-filter", "lucide:git-compare-arrows", "lucide:panels-top-left", "lucide:message-square-text", "lucide:list-checks", "lucide:book-open-check", "lucide:arrow-right"] } },
  colorMode: { preference: 'dark', fallback: 'dark', storage: 'sessionStorage', storageKey: 'magister-color-mode' },
  runtimeConfig: { public: { repositoryUrl: 'https://github.com/marianovicencio/CIE10--SNOMEDCT_mapper' } },
  compatibilityDate: '2026-11-13',
  app: { head: { htmlAttrs: { lang: 'es' }, title: 'Mapeo CIE-10 a SNOMED CT' } },
})
