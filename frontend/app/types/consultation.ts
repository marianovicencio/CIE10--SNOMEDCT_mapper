import type { ContextReview } from './context-review'
export type CodeSuggestion = { code: string, title: string }
export type Reference = { source?: string }
export type DocumentaryEntry = { text?: string, title?: string, term?: string, section?: string, scope?: string, origin?: string, inherited?: boolean, references?: Reference[], reference?: Reference, numbered_notes?: { text: string }[] }
export type CodeDocument = { source_snapshot_sha256?: string, code: string, title: string, edition: string, classification: { subdivisions?: { text: string }[], reference?: Reference }, tabular: Record<string, DocumentaryEntry[]>, manual_context: DocumentaryEntry[], index_context: DocumentaryEntry[], shared_context: DocumentaryEntry[], pagination: { total_records: number, next_offset: number | null } }
export type Candidate = { review?: ContextReview, retrievalRank?: number, id: string, term: string, rank: number, active: boolean, methods: { lexical: number | null, semantic: number | null }, matches: { query_id: string, term: string, rank: number, method: string }[] }
export type SearchResult = { status: string, code?: string, message?: string, target?: { version: string }, fusion?: { pool_concepts: number }, candidates?: Candidate[], queries?: { id: string, kind: string, text: string }[] }
export function documentTitle(document: CodeDocument) {
  return [document.title, ...(document.classification.subdivisions ?? []).map(row => row.text)].join(' — ')
}
// Presentation notices only. These labels never alter the backend assessment.
export function candidateNotice(candidate: Candidate): { label: string, tone: 'warning' | 'conflict' } | null {
  if (!candidate.active) return { label: 'Vigencia no verificada', tone: 'warning' }
  const review = candidate.review
  if (!review) return null
  if (review.status === 'excluded_by_explicit_constraint') return { label: 'Conflicto con la evidencia', tone: 'conflict' }
  if (review.constraint) return { label: 'Falta información', tone: 'warning' }
  if (['no_hierarchy_link_review', 'candidate_site_narrower_review', 'candidate_site_broader_review', 'multiple_sites_review'].includes(review.anatomy.status)) return { label: 'Revisar localización', tone: 'warning' }
  if (['negated', 'hypothetical', 'historical', 'uncertain', 'other_subject'].includes(review.input_scope)) return { label: 'Revisar contexto', tone: 'warning' }
  return null
}
