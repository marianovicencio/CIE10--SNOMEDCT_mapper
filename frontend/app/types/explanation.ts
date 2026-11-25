export interface ExplanationResult {
  status: 'explanation_available' | 'explanation_rejected' | 'explanation_unavailable'
  message?: string
  errors?: string[]
  generation_method?: 'literal_heading_comparison' | 'grammatical_heading_comparison' | 'conservative_documentary_fallback' | 'local_model' | 'openai_model' | 'explicit_local_anatomical_exclusion' | 'documentary_constraint' | 'manual_documentary_constraint' | 'index_documentary_constraint'
  automatic_comparison?: { assessment: 'compatible', text: string, evidence_refs: string[] } | null
  provider?: 'local' | 'openai'
  model?: string
  token_usage?: { input_tokens?: number, output_tokens?: number, total_tokens?: number, model: string }[]
  manual_context?: {
    scope: string
    selected_manual_items: number
    available_manual_items: number
    linked_context_pages_complete: boolean
    passed_to_model: boolean
    automatic_recoding: boolean
    items: { id: string, title: string, section: string, role: string, scope: string,
      text: string, provenance: string, requires_case_context: boolean,
      contains_worked_examples: boolean, cited: boolean, passed_to_model: boolean }[]
  }
  index_context?: {
    selected_index_items: number
    available_index_items: number
    linked_context_pages_complete: boolean
    passed_to_model: boolean
    usable_as_synonym: boolean
    items: { id: string, kind: string, role: string, route: string[], text: string,
      provenance: string, matched_columns: string[], cited: boolean, passed_to_model: boolean }[]
  }
  attributed_claims?: { text: string, evidence_refs: string[] }[]
  recovery_context_selection?: { policy: string, included_evidence_ids: string[], omitted_evidence_ids: string[], automatic_selection: boolean } | null
  recovered_after_validation?: boolean
  normalizations?: string[]
  elapsed_seconds?: number
  scope_note?: string
  analysis: {
    concept_id: string
    assessment: 'compatible' | 'incompatible' | 'undetermined'
    justification: string
    selection: 'proposed' | 'abstained' | 'not_requested'
    additional_detail_needed: string[]
    quotes: { evidence_id: string, text: string }[]
  } | null
  available_evidence?: { id: string, label: string, text: string, source: string }[]
  evidence?: { id: string, type: string, source: string, label?: string, role?: string, volume?: number, reading_text?: string }[]
}

export interface ExplanationState {
  loading: boolean
  result?: ExplanationResult
  error?: string
}

// Presentation only: a failed explanation is not evidence of missing clinical data.
export function explanationHeading(result?: ExplanationResult) {
  if (result?.generation_method === 'conservative_documentary_fallback') return 'No se pudo completar la comparación'
  const analysis = result?.analysis
  if (!analysis) return ''
  if (result?.recovery_context_selection) return 'Comparación con contexto acotado'
  if (analysis.assessment === 'incompatible') return 'Se detectó una incompatibilidad'
  if (analysis.assessment === 'undetermined') return 'Falta información para decidir'
  return analysis.selection === 'abstained' ? 'La evidencia no permite proponerlo todavía' : 'Coincidencia respaldada por la evidencia'
}
