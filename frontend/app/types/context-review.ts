export type ReviewStatus = 'no_detected_conflict' | 'requires_review' | 'excluded_by_explicit_constraint'
export interface FindingSite { concept_id: string, descriptions: string[] }
export type ComparisonStatus = 'same_wording' | 'supported_by_hierarchy' | 'candidate_narrower' | 'candidate_broader' | 'candidate_detail' | 'not_explicit' | 'different_wording' | 'conflict' | 'context'
export interface ComparisonSource { id: string, type: string, label: string, text: string, provenance?: string, role?: string, volume?: number }
export interface ScopeComparison {
  policy: string
  summary: { status: 'supported' | 'review' | 'conflict', title: string, text: string }
  dimensions: { id: string, label: string, status: ComparisonStatus, cie: { text: string }, candidate: { text: string, detail?: string }, reading: string, evidence_refs: string[] }[]
  sources: ComparisonSource[]
  input: { text: string, scope: string, evidence_ref: string } | null
  automatic_selection: false
  positive_mapping_approved: false
}
export interface ContextReview {
  comparison?: ScopeComparison | null
  automatic_comparison?: { kind: string, text: string } | null
  status: ReviewStatus
  input_scope: string
  anatomy: { status: string, proves_disjointness: boolean }
  finding_sites: { cie: FindingSite[], candidate: FindingSite[] }
  constraint: { rule_id: string, assessment: string, justification: string, additional_detail_needed?: string[] } | null
  citations: { id: string, type: string, label?: string, role?: string, text?: string, provenance?: string, volume?: number }[]
  positive_mapping_approved: false
}
export interface CandidateReviewResult {
  status: 'candidate_context_review_available'
  code: string
  source_snapshot_sha256: string
  target_version: string
  candidates: { id: string, retrieval_rank: number, rank: number, review: ContextReview }[]
  candidate_set_preserved: true
  automatic_selection: false
}
export const reviewLabels: Record<ReviewStatus, string> = {
  no_detected_conflict: 'Pendiente de revisión clínica',
  requires_review: 'Requiere aclaración',
  excluded_by_explicit_constraint: 'No propuesto'
}
