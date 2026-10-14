import type { Analytics, AssessmentListItem, AssessmentView, AttemptResult, AttemptStart, Capabilities, ChatMessage, Citation, Conversation, Course, Dashboard, DocumentItem, EvaluationRun, EvaluationSource, ExplainMode, MediaToken, NextAssessment, RecommendationItem, RevisionCard, SlideView, StudyPlan, Topic, User } from "@/types";

const TOKEN_KEY = "nova.token";
// NOTE: a bearer token in localStorage is simple but readable by any script on the page (XSS).
// Acceptable for this local prototype; production should use httpOnly cookies. See docs/ARCHITECTURE.md.
export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function describe(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string; loc?: (string | number)[] };
    const field = first.loc?.filter((p) => p !== "body").join(".");
    return field ? `${field}: ${first.msg ?? "is invalid"}` : (first.msg ?? fallback);
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check that the backend is running on port 8000.");
  }
  if (res.status === 401 && token) {
    tokenStore.clear();
    window.dispatchEvent(new Event("nova:unauthorized"));
  }
  if (!res.ok) {
    let detail: unknown;
    try { detail = (await res.json()).detail; } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, describe(detail, `Request failed (${res.status}).`));
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  register: (b: { name: string; email: string; password: string }) =>
    request<{ access_token: string; user: User }>("/auth/register", { method: "POST", body: json(b) }),
  login: (b: { email: string; password: string }) =>
    request<{ access_token: string; user: User }>("/auth/login", { method: "POST", body: json(b) }),
  me: () => request<User>("/auth/me"),
  updateProfile: (b: Partial<Pick<User, "name" | "learning_goals" | "explanation_style" | "language" | "onboarded">>) =>
    request<User>("/users/me", { method: "PATCH", body: json(b) }),
  exportData: () => request<unknown>("/users/me/export"),
  deleteAccount: () => request<void>("/users/me", { method: "DELETE" }),

  dashboard: () => request<Dashboard>("/dashboard"),
  studyPlan: (courseId: string, exam_date: string, hours_per_day: number) =>
    request<StudyPlan>(`/courses/${courseId}/study-plan`, { method: "POST", body: json({ exam_date, hours_per_day }) }),
  revisionCards: (courseId: string) => request<RevisionCard[]>(`/courses/${courseId}/revision-cards`),

  courses: () => request<Course[]>("/courses"),
  course: (id: string) => request<Course>(`/courses/${id}`),
  createCourse: (b: { title: string; description?: string }) => request<Course>("/courses", { method: "POST", body: json(b) }),
  updateCourse: (id: string, b: { title?: string; description?: string }) =>
    request<Course>(`/courses/${id}`, { method: "PATCH", body: json(b) }),
  deleteCourse: (id: string) => request<void>(`/courses/${id}`, { method: "DELETE" }),

  documents: (courseId: string) => request<DocumentItem[]>(`/courses/${courseId}/documents`),
  upload: (courseId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<DocumentItem>(`/courses/${courseId}/documents`, { method: "POST", body: fd });
  },
  replaceDocument: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<DocumentItem>(`/documents/${id}/replace`, { method: "POST", body: fd });
  },
  retryDocument: (id: string) => request<DocumentItem>(`/documents/${id}/retry`, { method: "POST" }),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),

  capabilities: () => request<Capabilities>("/system/capabilities"),

  topics: (courseId: string) => request<Topic[]>(`/courses/${courseId}/topics`),
  createTopic: (courseId: string, b: { name: string; description?: string; parent_id?: string | null }) =>
    request<Topic>(`/courses/${courseId}/topics`, { method: "POST", body: json(b) }),
  patchTopic: (id: string, b: { name?: string; description?: string }) => request<{ ok: boolean }>(`/topics/${id}`, { method: "PATCH", body: json(b) }),
  deleteTopic: (id: string) => request<void>(`/topics/${id}`, { method: "DELETE" }),
  addPrerequisite: (id: string, prerequisite_id: string) =>
    request<{ ok: boolean }>(`/topics/${id}/prerequisites`, { method: "POST", body: json({ prerequisite_id }) }),
  removePrerequisite: (id: string, pid: string) => request<void>(`/topics/${id}/prerequisites/${pid}`, { method: "DELETE" }),
  topicSources: (id: string) => request<Citation[]>(`/topics/${id}/sources`),
  rebuildTopics: (courseId: string) => request<{ topics: number; method: string }>(`/courses/${courseId}/topics/rebuild`, { method: "POST" }),
  moveChunk: (chunkId: string, topic_id: string | null) =>
    request<{ ok: boolean }>(`/chunks/${chunkId}`, { method: "PATCH", body: json({ topic_id }) }),

  suggestions: (courseId: string) => request<string[]>(`/courses/${courseId}/suggestions`),
  conversations: (courseId: string) => request<Conversation[]>(`/courses/${courseId}/conversations`),
  messages: (conversationId: string) => request<ChatMessage[]>(`/conversations/${conversationId}/messages`),
  deleteConversation: (id: string) => request<void>(`/conversations/${id}`, { method: "DELETE" }),
  chat: (courseId: string, b: { question: string; conversation_id?: string | null; topic_id?: string | null; mode?: ExplainMode | null; allow_general?: boolean }) =>
    request<{ conversation_id: string; user_message: ChatMessage; assistant_message: ChatMessage }>(`/courses/${courseId}/chat`, { method: "POST", body: json(b) }),

  /** Full text of one stored passage (citations only carry a short excerpt). */
  openChunkText: async (chunkId: string) => (await request<{ text: string }>(`/chunks/${chunkId}`)).text,

  createAssessment: (courseId: string, b: { mode: string; topic_ids: string[]; num_questions: number; difficulty: string; types: string[]; timed: boolean; time_limit_minutes?: number | null }) =>
    request<AssessmentView>(`/courses/${courseId}/assessments`, { method: "POST", body: json(b) }),
  assessments: (courseId: string) => request<AssessmentListItem[]>(`/courses/${courseId}/assessments`),
  assessmentCourse: async (assessmentId: string) => {
    const a = await request<AssessmentView>(`/assessments/${assessmentId}`);
    return { course_id: a.course_id };
  },
  beginAttempt: (assessmentId: string) => request<AttemptStart>(`/assessments/${assessmentId}/attempts`, { method: "POST" }),
  submitAttempt: (attemptId: string, answers: Record<string, string | null>) =>
    request<AttemptResult>(`/attempts/${attemptId}/submit`, { method: "POST", body: json({ answers }) }),
  attemptResult: (attemptId: string) => request<AttemptResult>(`/attempts/${attemptId}`),
  analytics: (courseId: string) => request<Analytics>(`/courses/${courseId}/analytics`),
  evaluationSources: (courseId: string, q = "", offset = 0) => {
    const params = new URLSearchParams({ limit: "100", offset: String(offset) });
    if (q.trim()) params.set("q", q.trim());
    return request<{ total: number; limit: number; offset: number; items: EvaluationSource[] }>(`/courses/${courseId}/evaluation-sources?${params}`);
  },
  evaluations: (courseId: string) => request<EvaluationRun[]>(`/courses/${courseId}/evaluations`),
  runRetrievalEvaluation: (courseId: string, cases: { question: string; reference_answer: string | null; relevant_chunk_ids: string[]; should_refuse: boolean }[]) =>
    request<EvaluationRun>(`/courses/${courseId}/evaluations/retrieval`, { method: "POST", body: json({ cases }) }),
  runPersonalizationEvaluation: (courseId: string, b: { sessions: number; questions_per_session: number; seed: number }) =>
    request<EvaluationRun>(`/courses/${courseId}/evaluations/personalization`, { method: "POST", body: json(b) }),
  nextAssessment: (courseId: string) => request<NextAssessment | null>(`/courses/${courseId}/next-assessment`),
  recommendations: (courseId: string) => request<RecommendationItem[]>(`/courses/${courseId}/recommendations`),
  dismissRecommendation: (id: string) => request<void>(`/recommendations/${id}/dismiss`, { method: "POST" }),
  chunk: (chunkId: string) => request<Citation & { text: string }>(`/chunks/${chunkId}`),

  mediaToken: (docId: string) => request<MediaToken>(`/documents/${docId}/media-token`),
  slide: (docId: string, n: number) => request<SlideView>(`/documents/${docId}/slides/${n}`),

  /** Fetches the original file with auth and opens it in a new tab (a plain link can't send the token). */
  async openDocument(id: string) {
    const token = tokenStore.get();
    const res = await fetch(`/api/documents/${id}/file`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!res.ok) throw new ApiError(res.status, "Couldn't open this file.");
    const url = URL.createObjectURL(await res.blob());
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  },
};
