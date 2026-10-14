import { ArrowRight, CheckCircle2, CircleDashed, Clock, Lightbulb, XCircle } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { MasteryNote } from "@/components/MasteryNote";
import { SourceViewer, locationLabel } from "@/components/source/SourceViewer";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorState, ProgressBar, Skeleton } from "@/components/ui/Feedback";
import { useAsync } from "@/hooks/useAsync";
import { useToast } from "@/hooks/useToast";
import { MODE_LABEL, pct } from "@/lib/mastery";
import { ApiError, api } from "@/services/api";
import type { Citation, NextAssessment, ResultQuestion } from "@/types";

function Ring({ value }: { value: number }) {
  const r = 44, c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 110 110" className="h-28 w-28" role="img" aria-label={`Accuracy ${pct(value)}`}>
      <circle cx="55" cy="55" r={r} fill="none" stroke="#e8e7fb" strokeWidth="10" />
      <circle cx="55" cy="55" r={r} fill="none" stroke={value >= 0.75 ? "#047857" : value >= 0.4 ? "#5b50e0" : "#b45309"} strokeWidth="10" strokeLinecap="round"
        strokeDasharray={`${c * value} ${c}`} transform="rotate(-90 55 55)" />
      <text x="55" y="62" textAnchor="middle" fontSize="22" fontWeight="700" fill="#0f172a">{pct(value)}</text>
    </svg>
  );
}

function QuestionReview({ q, onOpen }: { q: ResultQuestion; onOpen: (c: Citation) => void }) {
  const status = !q.answered ? { icon: <CircleDashed className="h-4 w-4" />, tone: "neutral" as const, text: "Not answered" }
    : q.is_correct ? { icon: <CheckCircle2 className="h-4 w-4" />, tone: "ok" as const, text: "Correct" }
    : (q.score ?? 0) > 0 ? { icon: <CircleDashed className="h-4 w-4" />, tone: "warn" as const, text: "Partly correct" }
    : { icon: <XCircle className="h-4 w-4" />, tone: "bad" as const, text: "Incorrect" };
  const missing = (q.feedback.missing as string[] | undefined) ?? [];
  const rubricReview = q.feedback.llm_rubric_review as { rationales?: { concept: string; evidence: string; reason: string }[] } | undefined;
  const rubricRationales = rubricReview?.rationales ?? [];
  return (
    <li className="card p-5">
      <div className="flex flex-wrap items-center gap-2"><Badge tone={status.tone} icon={status.icon}>{status.text}</Badge><Badge tone="neutral">{q.topic_name ?? "General"}</Badge><Badge tone="indigo">{q.difficulty}</Badge>
        {q.answered && q.score != null && q.score > 0 && q.score < 1 && <span className="text-xs text-ink-muted">{pct(q.score)} credit</span>}</div>
      <p className="mt-3 whitespace-pre-wrap font-medium">{q.text}</p>
      <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
        <div><dt className="text-ink-muted">Your answer</dt><dd className={q.answered ? "" : "text-ink-muted"}>{q.your_answer ?? "No answer"}</dd></div>
        <div><dt className="text-ink-muted">Correct answer</dt><dd className="font-medium text-ok">{q.correct_answer}</dd></div>
      </dl>
      {missing.length > 0 && <p className="mt-2 text-sm text-ink-muted">Missing: {missing.join(", ")}</p>}
      {rubricRationales.length > 0 && <div className="mt-3 rounded-ctl border border-nova-100 bg-nova-50 px-4 py-3 text-sm">
        <p className="font-medium text-nova-800">AI-assisted rubric review (partial-credit adjustment)</p>
        <ul className="mt-2 space-y-2">{rubricRationales.map((item, index) => <li key={`${item.concept}-${index}`}>
          <span className="font-medium">{item.concept}:</span> {item.reason}<span className="mt-0.5 block text-xs text-ink-muted">Your answer: “{item.evidence}”</span>
        </li>)}</ul>
      </div>}
      <p className="mt-3 rounded-ctl bg-slate-50 px-4 py-3 text-sm text-ink-soft">{q.explanation}</p>
      {q.misconception && <p className="mt-2 text-sm text-warn">{q.misconception}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        {q.source_removed ? <span className="text-ink-muted">The source file for this question was removed.</span> : <span className="text-ink-muted">Source:</span>}
        {q.citations.map((c) => <button key={c.n} onClick={() => onOpen(c)} className="rounded-full border border-line bg-white px-3 py-1 text-xs hover:border-nova-500 hover:text-nova-700">{c.filename} · {locationLabel(c)}</button>)}
      </div>
    </li>
  );
}

export default function Results() {
  const { tid = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const res = useAsync(() => api.attemptResult(tid), [tid]);
  const [open, setOpen] = useState<Citation | null>(null);
  const [busy, setBusy] = useState(false);
  const [courseId, setCourseId] = useState<string | null>(null);

  const r = res.data;
  useAsync(async () => { if (r) setCourseId((await api.assessmentCourse(r.assessment_id)).course_id); return null; }, [r?.assessment_id]);

  async function startNext(n: NextAssessment) {
    setBusy(true);
    try {
      const created = await api.createAssessment(courseId ?? (await api.assessmentCourse(r!.assessment_id)).course_id, { mode: n.mode, topic_ids: n.topic_ids, num_questions: n.num_questions, difficulty: n.difficulty, types: n.types, timed: false });
      navigate(`/assessments/${created.id}/take`);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Couldn't start the next assessment."); setBusy(false); }
  }

  if (res.error) return <ErrorState message={res.error.message} onRetry={res.reload} />;
  if (!r) return <div className="mx-auto max-w-4xl space-y-4"><Skeleton className="h-40" /><Skeleton className="h-64" /></div>;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="card flex flex-wrap items-center gap-6 p-6">
        <Ring value={r.accuracy} />
        <div className="min-w-0 flex-1">
          <p className="text-sm text-ink-muted">{MODE_LABEL[r.mode] ?? r.mode} results</p>
          <h1 className="text-2xl font-semibold">{r.score % 1 === 0 ? r.score : r.score.toFixed(1)} of {r.max_score} points</h1>
          <p className="mt-1 text-ink-muted">{r.correct} correct · {r.answered} of {r.total} answered</p>
          {r.overtime_seconds > 0 && <p className="mt-2 inline-flex items-center gap-1.5 text-sm text-warn"><Clock className="h-4 w-4" aria-hidden />Submitted {Math.round(r.overtime_seconds)} s after the time limit.</p>}
        </div>
        {courseId && <Link to={`/courses/${courseId}/analytics`} className="text-sm font-medium text-nova-600 hover:underline">View analytics</Link>}
      </header>

      <div className="grid gap-6 md:grid-cols-2">
        <section className="card p-6" aria-labelledby="tp-h">
          <h2 id="tp-h" className="text-base font-semibold">Performance by topic</h2>
          <ul className="mt-4 space-y-4">{r.topic_performance.map((t) => (
            <li key={t.topic_id ?? "none"}><div className="flex justify-between text-sm"><span className="font-medium">{t.topic_name}</span><span className="text-ink-muted">{t.correct}/{t.total} correct</span></div>
              <div className="mt-1.5"><ProgressBar value={t.accuracy ?? 0} tone={(t.accuracy ?? 0) >= 0.75 ? "ok" : (t.accuracy ?? 0) < 0.4 ? "warn" : "indigo"} /></div></li>))}</ul>
        </section>
        <section className="card p-6" aria-labelledby="mc-h">
          <h2 id="mc-h" className="text-base font-semibold">Updated mastery estimates</h2>
          {r.mastery_changes.length === 0 ? <p className="mt-3 text-sm text-ink-muted">Nothing was answered, so no estimate changed.</p> :
            <ul className="mt-4 space-y-3">{r.mastery_changes.map((m) => (
              <li key={m.topic_id} className="flex items-center justify-between gap-3 text-sm"><span className="font-medium">{m.topic_name}</span>
                <span className="flex items-center gap-2 tabular-nums"><span className="text-ink-muted">{pct(m.before)}</span><ArrowRight className="h-3.5 w-3.5 text-ink-muted" aria-hidden />
                  <Badge tone={m.after >= m.before ? "ok" : "warn"}>{pct(m.after)} est.</Badge></span></li>))}</ul>}
          <div className="mt-4"><MasteryNote text={r.estimate_note} /></div>
        </section>
      </div>

      <section className="card p-6" aria-labelledby="rec-h">
        <h2 id="rec-h" className="flex items-center gap-2 text-base font-semibold"><Lightbulb className="h-4 w-4 text-nova-600" aria-hidden />What to do next</h2>
        {r.recommendations.length === 0 ? <p className="mt-2 text-sm text-ink-muted">No recommendations yet.</p> :
          <ul className="mt-3 space-y-3">{r.recommendations.map((x) => (
            <li key={x.id} className="flex flex-wrap items-center justify-between gap-3 text-sm"><span className="min-w-0 flex-1 text-ink-soft">{x.reason}</span>
              {x.chunk_id && <Button size="sm" variant="secondary" onClick={() => api.chunk(x.chunk_id!).then((c) => setOpen({ ...c, n: 0 })).catch(() => toast.error("Couldn't open that passage."))}>Open passage</Button>}</li>))}</ul>}
        {r.next_assessment && <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-ctl bg-nova-50 p-4"><p className="min-w-0 flex-1 text-sm text-nova-800"><strong>Your personalised next quiz.</strong> {r.next_assessment.reason}</p>
          <Button loading={busy} onClick={() => void startNext(r.next_assessment!)}>Start it</Button></div>}
      </section>

      <section aria-labelledby="rev-h"><h2 id="rev-h" className="mb-3 text-base font-semibold">Review every question</h2>
        <ul className="space-y-3">{r.questions.map((q) => <QuestionReview key={q.id} q={q} onOpen={setOpen} />)}</ul></section>

      <Dialog open={open !== null} onClose={() => setOpen(null)} title="Source">{open && <div className="max-h-[70vh] overflow-y-auto"><SourceViewer citation={open} /></div>}</Dialog>
    </div>
  );
}
