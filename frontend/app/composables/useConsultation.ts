import type { ExplanationResult, ExplanationState } from '~/types/explanation'
import type { CandidateReviewResult } from '~/types/context-review'

import type { CodeDocument as Doc, Candidate, SearchResult as Result, CodeSuggestion } from '~/types/consultation'
import { documentTitle as codeLabel } from '~/types/consultation'

export function useConsultation() {
const code = ref('')
const suggestions = ref<CodeSuggestion[]>([])
const suggestionsLoading = ref(false)
const suggestionsUnavailable = ref(false)
const diagnostic = ref('')
type ExplanationContext = { code: string, diagnostic_text: string, source_snapshot_sha256: string, target_version: string }
const explanationContext = ref<ExplanationContext | null>(null)
const submittedDiagnostic = ref('')
const explanations = ref<Record<string, ExplanationState>>({})
const explanationBusy = ref(false)
const contextLoading = ref(false)
const contextError = ref('')
const contextCompleted = ref(false)
const searchStage = ref<'documents' | 'candidates' | 'context' | null>(null)
const progressLabel = computed(() => searchStage.value === 'documents' ? 'Consultando la fuente CIE-10…' : searchStage.value === 'context' ? 'Revisando coincidencias y diferencias…' : 'Buscando candidatos en SNOMED CT…')
let contextController: AbortController | null = null
function clearContextReview() {
  contextController?.abort()
  contextController = null
  contextLoading.value = false
  contextError.value = ''
  contextCompleted.value = false
}
const explanationProvider = ref('local')
const externalConsent = ref(false)
watch(explanationProvider, () => {
  explanationController?.abort()
  explanationController = null
  explanationBusy.value = false
  explanations.value = {}
  externalConsent.value = false
})

let explanationController: AbortController | null = null

function clearExplanations() {
  explanationController?.abort()
  explanationController = null
  explanationBusy.value = false
  explanations.value = {}
  explanationContext.value = null
}

onBeforeUnmount(() => { clearExplanations(); clearContextReview() })

async function reviewCurrentCandidates() {
  const context = explanationContext.value
  const current = result.value
  if (!context || !current?.candidates?.length || contextLoading.value) return
  const controller = new AbortController()
  contextController = controller
  contextLoading.value = true
  contextError.value = ''
  contextCompleted.value = false
  try {
    const response = await $fetch<CandidateReviewResult>('/api/revision-contextual', {
      method: 'POST', body: { ...context, concept_ids: current.candidates.map(c => c.id) }, signal: controller.signal, retry: 0
    })
    if (controller.signal.aborted || result.value !== current || explanationContext.value !== context) return
    const ids = current.candidates.map(c => c.id)
    if (response.status !== 'candidate_context_review_available' || response.code !== context.code || response.source_snapshot_sha256 !== context.source_snapshot_sha256 || response.target_version !== context.target_version || response.candidates.length !== ids.length || new Set(response.candidates.map(c => c.id)).size !== ids.length || response.candidates.some(c => !ids.includes(c.id)))
      throw new Error('Revisión contextual inconsistente')
    const byId = new Map(current.candidates.map(c => [c.id, c]))
    result.value = { ...current, candidates: response.candidates.map(c => ({ ...byId.get(c.id)!, rank: c.rank, retrievalRank: byId.get(c.id)!.retrievalRank ?? c.retrieval_rank, review: c.review })) }
    contextCompleted.value = true
  } catch (error) {
    if (!controller.signal.aborted && result.value === current)
      contextError.value = errorText(error) || 'No se pudo completar el contraste contextual.'
  } finally {
    if (contextController === controller) { contextLoading.value = false; contextController = null }
  }
}

async function explain(candidate: Candidate, regenerate = false) {
  const context = explanationContext.value
  if (!context || contextLoading.value || pendingCodeChange.value || candidate.review?.status === 'excluded_by_explicit_constraint' || (explanationProvider.value === 'openai' && !externalConsent.value) || explanationBusy.value || (explanations.value[candidate.id]?.result?.analysis && !regenerate)) return
  const controller = new AbortController()
  explanationController = controller
  explanationBusy.value = true
  explanations.value[candidate.id] = { loading: true }
  try {
    const response = await $fetch<ExplanationResult>('/api/explicacion', {
      method: 'POST', body: { ...context, concept_id: candidate.id, provider: explanationProvider.value, external_consent: externalConsent.value }, signal: controller.signal, retry: 0
    })
    if (!controller.signal.aborted && explanationContext.value === context)
      explanations.value[candidate.id] = { loading: false, result: response }
  } catch (error) {
    if (!controller.signal.aborted && explanationContext.value === context)
      explanations.value[candidate.id] = { loading: false, error: errorText(error) }
  } finally {
    if (explanationController === controller) {
      explanationBusy.value = false
      explanationController = null
    }
  }
}

const doc = ref<Doc | null>(null)
const result = ref<Result | null>(null)
const busy = ref(false)
const loadingMore = ref(false)
const message = ref('')
const documentMessage = ref('')
const focusId = ref<string | null>(null)
const terms = computed(() => result.value?.candidates ?? [])
const selected = computed(() => terms.value.find(x => x.id === focusId.value))
const versionDate = computed(() => result.value?.target?.version?.split('/').at(-1))
const cieEdition = useState('cie-edition', () => 'OPS/OMS CIE-10 2018')
const snomedRelease = useState('snomed-release', () => '20261110')
watch([() => doc.value?.edition, versionDate], ([edition, release]) => {
  if (edition) cieEdition.value = edition
  if (release) snomedRelease.value = release
}, { immediate: true })
const submittedCode = computed(() => doc.value?.code ?? result.value?.code)
const pendingCodeChange = computed(() => Boolean(submittedCode.value && (submittedCode.value !== code.value || submittedDiagnostic.value !== diagnostic.value)))
const enteredTitle = computed(() => {
  if (doc.value?.code === code.value) return codeLabel(doc.value)
  return suggestions.value.find(item => item.code === code.value)?.title
})

function cleanCode(value: string) {
  const upper = value.trim().toUpperCase()
  return /^(?:[A-Z](?:[0-9]{0,2}|[0-9]{2}\.[0-9]{0,2}))?$/.test(upper) ? upper : code.value
}

function restrictCodeInput(event: Event) {
  if (!(event.target instanceof HTMLInputElement) || (event as InputEvent).isComposing) return
  const input = event.target
  const cleaned = cleanCode(input.value)
  if (input.value === cleaned) return
  const cursor = Math.min(input.selectionStart ?? cleaned.length, cleaned.length)
  input.value = cleaned
  input.setSelectionRange(cursor, cursor)
}

watch(code, (prefix, _, onCleanup) => {
  suggestions.value = []
  suggestionsUnavailable.value = false
  suggestionsLoading.value = Boolean(prefix)
  if (!prefix) return

  const controller = new AbortController()
  const timer = setTimeout(async () => {
    try {
      const response = await $fetch<{ items: CodeSuggestion[] }>('/api/codigos', {
        query: { prefix }, signal: controller.signal, retry: 0
      })
      if (!controller.signal.aborted) suggestions.value = response.items
    } catch {
      if (!controller.signal.aborted) suggestionsUnavailable.value = true
    } finally {
      if (!controller.signal.aborted) suggestionsLoading.value = false
    }
  }, 100)
  onCleanup(() => {
    clearTimeout(timer)
    controller.abort()
  })
}, { immediate: import.meta.client })

function errorText(error: unknown) {
  const e = error as { data?: { message?: string } }
  return e.data?.message || 'No se pudo completar la consulta local.'
}
async function search(value = code.value, text = diagnostic.value) {
  if (busy.value) return
  const clean = value.trim().toUpperCase()
  if (!/^[A-Z][0-9]{2}(?:\.[0-9]{1,2})?$/.test(clean)) {
    message.value = 'Ingresa un código CIE-10 individual, como E10.7.'
    return
  }
  code.value = clean
  message.value = ''
  documentMessage.value = ''
  clearExplanations()
  clearContextReview()
  searchStage.value = 'documents'
  submittedDiagnostic.value = text
  busy.value = true
  result.value = null
  doc.value = null
  focusId.value = null
  try {
    doc.value = await $fetch<Doc>('/api/documento/' + encodeURIComponent(clean))
    searchStage.value = 'candidates'
    const response = await $fetch<Result>('/api/candidatos', { method: 'POST', body: { code: clean, diagnostic_text: text }, retry: 0 })
    if (response.status === 'blocked') message.value = response.message || 'La búsqueda quedó bloqueada.'
    else {
      result.value = response
      if (doc.value.source_snapshot_sha256 && response.target?.version)
        explanationContext.value = { code: clean, diagnostic_text: text, source_snapshot_sha256: doc.value.source_snapshot_sha256, target_version: response.target.version }
      searchStage.value = 'context'
      await reviewCurrentCandidates()
    }
  } catch (e) { message.value = errorText(e) }
  finally { busy.value = false; searchStage.value = null }
}
async function more() {
  const current = doc.value
  const next = current?.pagination.next_offset
  if (!current || next == null || loadingMore.value) return
  loadingMore.value = true
  documentMessage.value = ''
  try {
    const page = await $fetch<Doc>('/api/documento/' + encodeURIComponent(current.code), { query: { offset: next } })
    if (doc.value !== current) return
    doc.value = {
      ...current, pagination: page.pagination,
      manual_context: [...current.manual_context, ...page.manual_context],
      index_context: [...current.index_context, ...page.index_context],
      shared_context: [...new Map([...current.shared_context, ...page.shared_context].map(x => [JSON.stringify(x), x])).values()]
    }
  } catch (e) { documentMessage.value = errorText(e) }
  finally { loadingMore.value = false }
}

return { code, diagnostic, suggestions, suggestionsLoading, suggestionsUnavailable,
  enteredTitle, cleanCode, restrictCodeInput, explanationProvider, externalConsent,
  doc, result, terms, selected, focusId, busy, contextLoading, contextError,
  contextCompleted, progressLabel, message, pendingCodeChange, submittedCode,
  explanationContext, explanations, explanationBusy, loadingMore, documentMessage,
  search, explain, reviewCurrentCandidates, more }
}
