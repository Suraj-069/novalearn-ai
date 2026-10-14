import { ClipboardCheck, Clock, Play, Sparkles, Target } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { MasteryNote } from "@/components/MasteryNote";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { useAsync } from "@/hooks/useAsync";
import { useToast } from "@/hooks/useToast";
import { MODE_LABEL } from "@/lib/mastery";
import { timeAgo } from "@/lib/format";
import { ApiError, api } from "@/services/api";
import type { NextAssessment, QuestionType } from "@/types";

const TYPES: { id: QuestionType; label: string; note?: string }[] = [
  { id: "mcq", label: "Multiple choice" }, { id: "short_answer", label: "Short answer" }, { id: "numerical", label: "Numerical", note: "needs a language model" },
];
const DIFFS = [{ id: "mixed", label: "Mixed" }, { id: "easy", label: "Easy" }, { id: "medium", label: "Medium" }, { id: "hard", label: "Hard" }];

export default function Assessments() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const course = useAsync(() => api.course(id), [id]);
  const topics = useAsync(() => api.topics(id), [id]);
  const list = useAsync(() => api.assessments(id), [id]);
  const next = useAsync(() => api.nextAssessment(id), [id]);
  const caps = useAsync(() => api.capabilities(), []);

  const [mode, setMode] = useState<"quiz" | "mock_exam" | "diagnostic">(params.get("diagnostic") ? "diagnostic" : "quiz");
  const [count, setCount] = useState(8);
  const [difficulty, setDifficulty] = useState("mixed");
  const [types, setTypes] = useState<QuestionType[]>(["mcq", "short_answer"]);
  const [picked, setPicked] = useState<string[]>([]);
  const [timed, setTimed] = useState(false);
  const [minutes, setMinutes] = useState(15);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (mode === "mock_exam") setTimed(true); if (mode === "diagnostic") setTimed(false); }, [mode]);

  const topLevel = (topics.data ?? []).filter((t) => !t.parent_id && t.chunk_count > 0);
  const hasLLM = caps.data?.llm.configured ?? false;
  const toggle = <T,>(l: T[], v: T) => (l.includes(v) ? l.filter((x) => x !== v) : [...l, v]);

  async function start(cfg: { mode: string; topic_ids: string[]; num_questions: number; difficulty: string; types: string[]; timed: boolean; minutes?: number | null }) {
    setBusy(true);
    try {
      const a = await api.createAssessment(id, { mode: cfg.mode, topic_ids: cfg.topic_ids, num_questions: cfg.num_questions, difficulty: cfg.difficulty, types: cfg.types, timed: cfg.timed, time_limit_minutes: cfg.timed ? cfg.minutes : null });
      (a.warnings ?? []).forEach((w) => toast.error(w));
      navigate(`/assessments/${a.id}/take`);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Couldn't create the assessment."); setBusy(false); }
  }

  const startForm = () => start({ mode, topic_ids: picked, num_questions: count, difficulty, types, timed, minutes });
  const startSuggested = (n: NextAssessment) => start({ mode: n.mode, topic_ids: n.topic_ids, num_questions: n.num_questions, difficulty: n.difficulty, types: n.types, timed: false });

  if (course.error) return <ErrorState message={course.error.message} onRetry={course.reload} />;
  const noContent = topics.data && topLevel.length === 0;

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/courses/${id}`} className="text-sm text-ink-muted hover:text-ink">← {course.data?.title ?? "Course"}</Link>
        <h1 className="text-2xl font-semibold sm:text-3xl">Practice and assessments</h1>
        <p className="mt-1 text-ink-muted">Questions are built from your own material, checked against it, and never repeated.</p>
      </div>

      {noContent ? (
        <div className="card"><EmptyState icon={<ClipboardCheck className="h-5 w-5" />} title="Nothing to quiz yet" action={<Link to={`/courses/${id}`}><Button>Go to course material</Button></Link>}>Upload and index some material first.</EmptyState></div>
      ) : (<>
        {next.data && (
          <section className="rounded-card bg-gradient-to-br from-nova-700 via-nova-600 to-violet p-6 text-white shadow-card" aria-label="Recommended next assessment">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-start gap-4"><div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-white/15"><Sparkles className="h-5 w-5" aria-hidden /></div>
                <div><p className="text-sm text-white/70">{next.data.mode === "diagnostic" ? "Start here" : "Recommended next"}</p>
                  <h2 className="text-xl font-semibold">{next.data.mode === "diagnostic" ? "Take your diagnostic" : "Practice your weakest topics"}</h2>
                  <p className="mt-1 max-w-2xl text-white/80">{next.data.reason}</p></div></div>
              <button disabled={busy} onClick={() => startSuggested(next.data!)} className="inline-flex items-center gap-2 rounded-ctl bg-white px-4 py-2.5 text-sm font-semibold text-nova-700 hover:bg-nova-50 disabled:opacity-60">
                <Play className="h-4 w-4" aria-hidden />Start ({next.data.num_questions} questions)</button>
            </div>
          </section>)}

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          <section className="card p-6" aria-labelledby="new-h">
            <h2 id="new-h" className="text-base font-semibold">Build an assessment</h2>
            <div className="mt-5 space-y-6">
              <fieldset><legend className="mb-2 text-sm font-medium text-ink-soft">Mode</legend>
                <div className="grid gap-2 sm:grid-cols-3" role="radiogroup">
                  {(["quiz", "mock_exam", "diagnostic"] as const).map((m) => (
                    <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => setMode(m)}
                      className={`rounded-ctl border p-3 text-left text-sm ${mode === m ? "border-nova-600 bg-nova-50" : "border-line hover:border-slate-300"}`}>
                      <div className="font-medium">{MODE_LABEL[m]}</div>
                      <div className="mt-0.5 text-xs text-ink-muted">{m === "quiz" ? "Practice, adapts to your weak topics" : m === "mock_exam" ? "Timed, exam conditions" : "Even coverage to find your starting point"}</div>
                    </button>))}
                </div></fieldset>

              <fieldset><legend className="mb-2 text-sm font-medium text-ink-soft">Topics <span className="font-normal text-ink-muted">(none selected = all)</span></legend>
                {topics.loading && <Skeleton className="h-9" />}
                <div className="flex flex-wrap gap-2">
                  {topLevel.map((t) => (
                    <button key={t.id} type="button" aria-pressed={picked.includes(t.id)} onClick={() => setPicked(toggle(picked, t.id))}
                      className={`rounded-full border px-3.5 py-1.5 text-sm ${picked.includes(t.id) ? "border-nova-600 bg-nova-50 text-nova-700" : "border-line bg-white text-ink-soft hover:border-slate-300"}`}>
                      {t.name}{t.mastery != null && <span className="ml-1.5 text-xs text-ink-muted">{Math.round(t.mastery * 100)}%</span>}</button>))}
                </div></fieldset>

              <div className="grid gap-5 sm:grid-cols-2">
                <div><label htmlFor="n" className="mb-1.5 block text-sm font-medium text-ink-soft">Number of questions: {count}</label>
                  <input id="n" type="range" min={1} max={30} value={count} onChange={(e) => setCount(Number(e.target.value))} className="w-full accent-nova-600" /></div>
                <div><label htmlFor="d" className="mb-1.5 block text-sm font-medium text-ink-soft">Difficulty</label>
                  <select id="d" value={difficulty} onChange={(e) => setDifficulty(e.target.value)} className="input">{DIFFS.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}</select></div>
              </div>

              <fieldset><legend className="mb-2 text-sm font-medium text-ink-soft">Question types</legend>
                <div className="flex flex-wrap gap-3">
                  {TYPES.map((t) => { const off = t.id === "numerical" && !hasLLM; return (
                    <label key={t.id} className={`flex items-center gap-2 text-sm ${off ? "opacity-55" : ""}`}>
                      <input type="checkbox" disabled={off} checked={types.includes(t.id) && !off} onChange={() => setTypes(toggle(types, t.id))} />
                      {t.label}{off && <span className="text-xs text-ink-muted">({t.note})</span>}</label>); })}
                </div></fieldset>

              {!hasLLM && <p className="rounded-ctl bg-nova-50 px-4 py-3 text-sm text-nova-800">No language model is configured, so questions are fill-in-the-blank built from your material: easy = multiple choice, medium = one blank, hard = two blanks. Add a model in <code>.env</code> for richer questions and numerical problems.</p>}

              <div className="flex flex-wrap items-center gap-4">
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={timed} disabled={mode !== "quiz"} onChange={(e) => setTimed(e.target.checked)} />Timed</label>
                {timed && <label className="flex items-center gap-2 text-sm"><Clock className="h-4 w-4 text-ink-muted" aria-hidden /><input type="number" min={1} max={240} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} className="input !w-20 !py-1.5" aria-label="Minutes" />minutes</label>}
              </div>
              <Button loading={busy} disabled={types.filter((t) => t !== "numerical" || hasLLM).length === 0} onClick={startForm} icon={<Target className="h-4 w-4" />}>Generate and start</Button>
              <MasteryNote />
            </div>
          </section>

          <aside className="card h-fit p-6" aria-labelledby="hist-h">
            <h2 id="hist-h" className="text-base font-semibold">Your assessments</h2>
            {list.loading && !list.data && <Skeleton className="mt-3 h-20" />}
            {list.data?.length === 0 && <p className="mt-2 text-sm text-ink-muted">None yet. Take the diagnostic or build a quiz.</p>}
            <ul className="mt-3 divide-y divide-line">
              {list.data?.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 py-3 text-sm">
                  <div><div className="font-medium">{MODE_LABEL[a.mode] ?? a.mode} · {a.question_count} questions</div><div className="text-xs text-ink-muted">{timeAgo(a.created_at)}</div></div>
                  {a.status === "completed" ? <Link to={`/attempts/${a.attempt_id}`} className="flex items-center gap-2"><Badge tone="indigo">{a.score}/{a.max_score}</Badge><span className="text-xs font-medium text-nova-600 hover:underline">Review</span></Link>
                    : <Link to={`/assessments/${a.id}/take`} className="text-xs font-medium text-nova-600 hover:underline">{a.status === "in_progress" ? "Resume" : "Start"}</Link>}
                </li>))}
            </ul>
          </aside>
        </div>
      </>)}
    </div>
  );
}
