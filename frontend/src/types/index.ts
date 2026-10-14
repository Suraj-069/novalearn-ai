export interface User {
  id: string;
  name: string;
  email: string;
  learning_goals: string[];
  explanation_style: "simple" | "balanced" | "detailed" | "examples";
  language: string;
  onboarded: boolean;
}

export interface Job {
  id: string;
  status: "queued" | "processing" | "inspected" | "failed" | "indexed";
  stage: string;
  error: string | null;
  attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export type SourceType = "pdf" | "pptx" | "image" | "video" | "transcript";

export interface DocumentItem {
  id: string;
  course_id: string;
  original_filename: string;
  source_type: SourceType;
  mime_type: string;
  size_bytes: number;
  page_count: number | null;
  slide_count: number | null;
  duration_seconds: number | null;
  has_text_layer: boolean | null;
  file_meta: Record<string, unknown>;
  created_at: string;
  job: Job | null;
}

export interface Course {
  id: string;
  title: string;
  description: string;
  created_at: string;
  updated_at: string;
  document_count: number;
  topic_count: number;
  status_counts: Record<string, number>;
  source_counts: Record<string, number>;
}

export interface TopicMastery { topic_id: string; topic_name: string; course_id: string; mastery: number; updated_at: string }
export interface Activity { kind: "upload" | "assessment"; label: string; course_id: string; at: string }
export interface Recommendation { id: string; course_id: string; topic_id: string | null; kind: string; reason: string }
export interface AssessmentSummary { attempt_id: string; course_id: string; score: number; max_score: number; submitted_at: string }

export interface Dashboard {
  course_count: number;
  document_count: number;
  indexed_document_count: number;
  topic_count: number;
  mastery: TopicMastery[];
  weak_topics: TopicMastery[];
  recent_activity: Activity[];
  recommendations: Recommendation[];
  recent_assessments: AssessmentSummary[];
  upcoming_revisions: { id: string; course_id: string; topic_name: string | null; due_at: string; is_due: boolean; reason: string }[];
}

export interface StudyPlan {
  exam_date: string; hours_per_day: number; formula: string;
  days: { date: string; tasks: { topic_id: string; topic_name: string; minutes: number; estimated_recall: number; reason: string }[] }[];
}

export interface Citation {
  n: number;
  chunk_id: string;
  document_id: string;
  filename: string | null;
  source_type?: SourceType;
  page?: number | null;
  slide?: number | null;
  start_seconds?: number | null;
  end_seconds?: number | null;
  figure_ref?: string | null;
  ai_generated?: boolean;
  excerpt: string;
  available: boolean;
  text?: string;
}

export type AnswerMode = "llm" | "extractive" | "unsupported" | "general";
export type ExplainMode = "explain" | "simple" | "detailed" | "example" | "compare" | "summary";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  grounded: boolean | null;
  mode: AnswerMode | null;
  created_at: string;
}

export interface Conversation { id: string; title: string; topic_id: string | null; created_at: string }

export interface Topic {
  id: string;
  parent_id: string | null;
  name: string;
  description: string;
  origin: "auto" | "user";
  chunk_count: number;
  source_counts: Record<string, number>;
  documents: { id: string; filename: string; chunks: number }[];
  prerequisites: { id: string; name: string; origin: string }[];
  mastery: number | null;
  mastery_evidence: number;
}

export interface Capabilities {
  llm: { configured: boolean; provider: string | null; error?: string };
  embeddings: { provider: string | null; semantic: boolean };
  speech_to_text: { configured: boolean; provider: string };
  ocr: { available: boolean };
  ffmpeg: { available: boolean };
  vision: { enabled: boolean };
}

export interface SlideView { slide: number; of: number; title: string | null; text: string[]; notes: string | null }
export interface MediaToken { token: string; expires_in: number; source_type: SourceType; page_count: number | null; slide_count: number | null }

export type QuestionType = "mcq" | "short_answer" | "numerical";
export type Difficulty = "easy" | "medium" | "hard";
export interface QuestionView {
  id: string; position: number | null; text: string; question_type: QuestionType; difficulty: Difficulty;
  topic_id: string | null; topic_name: string | null; options: { id: string; text: string }[] | null; unit: string | null;
}
export interface AssessmentView {
  id: string; course_id: string; mode: "quiz" | "mock_exam" | "diagnostic"; timed: boolean; time_limit_seconds: number | null;
  created_at: string; generation: string | null; questions: QuestionView[];
  warnings?: string[]; rejected_candidates?: number;
}
export interface AttemptStart extends AssessmentView { attempt_id: string; started_at: string }
export interface AssessmentListItem {
  id: string; mode: string; timed: boolean; question_count: number; created_at: string;
  status: "not_started" | "in_progress" | "completed"; attempt_id: string | null; score: number | null; max_score: number | null;
}
export interface NextAssessment {
  mode: "quiz" | "diagnostic"; topic_ids: string[]; num_questions: number; difficulty: Difficulty | "mixed";
  types: QuestionType[]; reason: string;
}
export interface RecommendationItem {
  id: string; kind: string; reason: string; topic_id: string | null; chunk_id: string | null; due_at: string | null; evidence: Record<string, unknown>;
}
export interface RevisionCard {
  id: string; topic_id: string; topic: string; front: string; answer: string; explanation: string; citations: Citation[];
}
export interface ResultQuestion extends QuestionView {
  your_answer: string | null; answered: boolean; is_correct: boolean | null; score: number | null; correct_answer: string;
  explanation: string; citations: Citation[]; source_removed: boolean; feedback: Record<string, unknown>; misconception: string | null;
}
export interface AttemptResult {
  attempt_id: string; assessment_id: string; mode: string; submitted_at: string; score: number; max_score: number; accuracy: number;
  answered: number; total: number; correct: number; overtime_seconds: number; timed: boolean; questions: ResultQuestion[];
  topic_performance: { topic_id: string | null; topic_name: string; answered: number; correct: number; total: number; accuracy: number | null }[];
  mastery_changes: { topic_id: string; topic_name: string | null; before: number; after: number; questions: number }[];
  recommendations: RecommendationItem[]; next_assessment: NextAssessment | null; estimate_note: string;
}
export interface Analytics {
  mastery: { topic_id: string; topic_name: string; mastery: number | null; evidence: number; updated_at: string | null; status: "strong" | "developing" | "weak" | "not_assessed" }[];
  timeline: { at: string; topic_id: string; topic_name: string; mastery: number; attempt_id: string | null }[];
  assessments: { attempt_id: string; assessment_id: string; mode: string; submitted_at: string; score: number; max_score: number; accuracy: number }[];
  difficulty: { difficulty: Difficulty; answered: number; correct: number; accuracy: number | null }[];
  activity: { date: string; answers: number; attempts: number }[];
  strong: Analytics["mastery"]; weak: Analytics["mastery"];
  due_revisions: { id: string; topic_id: string | null; topic_name: string | null; due_at: string; reason: string; is_due: boolean }[];
  note: string;
}

export interface EvaluationMetric {
  name: string;
  value: number | null;
  available: boolean;
  unavailable_reason: string | null;
  sample_size: number | null;
  details: Record<string, unknown>;
}
export interface EvaluationRun {
  id: string;
  course_id: string | null;
  kind: "retrieval" | "personalization";
  status: "running" | "completed" | "failed";
  config: Record<string, unknown>;
  notes: string | null;
  created_at: string;
  finished_at: string | null;
  metrics: EvaluationMetric[];
}
export interface EvaluationSource {
  chunk_id: string;
  filename: string;
  source_type: SourceType;
  page: number | null;
  slide: number | null;
  start_seconds: number | null;
  end_seconds: number | null;
  figure_ref: string | null;
  ai_generated: boolean;
  topic_name: string | null;
  excerpt: string;
}
