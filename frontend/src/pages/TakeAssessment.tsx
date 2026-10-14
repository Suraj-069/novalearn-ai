import { ArrowLeft, ArrowRight, Clock, Send } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorState, Skeleton } from "@/components/ui/Feedback";
import { useAsync } from "@/hooks/useAsync";
import { useToast } from "@/hooks/useToast";
import { MODE_LABEL } from "@/lib/mastery";
import { ApiError, api } from "@/services/api";

const fmt = (s: number) => `${Math.floor(Math.max(0, s) / 60)}:${String(Math.floor(Math.max(0, s) % 60)).padStart(2, "0")}`;

export default function TakeAssessment() {
  const { aid = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const attempt = useAsync(() => api.beginAttempt(aid), [aid]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [i, setI] = useState(0);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [left, setLeft] = useState<number | null>(null);
  const submitted = useRef(false);

  const a = attempt.data;
  const qs = a?.questions ?? [];
  const answered = useMemo(() => qs.filter((q) => (answers[q.id] ?? "").trim() !== "").length, [qs, answers]);

  async function submit(auto = false) {
    if (!a || submitted.current) return;
    submitted.current = true; setBusy(true); setConfirm(false);
    try {
      const payload: Record<string, string | null> = {};
      qs.forEach((q) => { const v = (answers[q.id] ?? "").trim(); payload[q.id] = v === "" ? null : v; });
      const r = await api.submitAttempt(a.attempt_id, payload);
      if (auto) toast.success("Time's up. Your answers were submitted.");
      navigate(`/attempts/${r.attempt_id}`, { replace: true });
    } catch (e) { submitted.current = false; setBusy(false); toast.error(e instanceof ApiError ? e.message : "Couldn't submit your answers."); }
  }

  useEffect(() => {
    if (!a?.timed || !a.time_limit_seconds) return;
    const end = new Date(a.started_at).getTime() + a.time_limit_seconds * 1000;
    const tick = () => { const s = (end - Date.now()) / 1000; setLeft(s); if (s <= 0) void submit(true); };
    tick(); const t = setInterval(tick, 1000); return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a?.attempt_id]);

  if (attempt.error) return <ErrorState message={attempt.error.message} onRetry={attempt.reload} />;
  if (!a) return <div className="mx-auto max-w-2xl space-y-4"><Skeleton className="h-10" /><Skeleton className="h-64" /></div>;
  const q = qs[i];
  const set = (v: string) => setAnswers((m) => ({ ...m, [q.id]: v }));

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-xl font-semibold">{MODE_LABEL[a.mode]}</h1><p className="text-sm text-ink-muted">Question {i + 1} of {qs.length} · {answered} answered</p></div>
        {left != null && <Badge tone={left < 60 ? "warn" : "indigo"} icon={<Clock className="h-3 w-3" />}><span aria-live="off">{fmt(left)} left</span></Badge>}
      </header>

      <nav aria-label="Questions" className="flex flex-wrap gap-1.5">
        {qs.map((x, n) => (
          <button key={x.id} onClick={() => setI(n)} aria-label={`Question ${n + 1}${(answers[x.id] ?? "").trim() ? ", answered" : ""}`} aria-current={n === i}
            className={`h-8 w-8 rounded-lg text-xs font-medium ${n === i ? "bg-nova-600 text-white" : (answers[x.id] ?? "").trim() ? "bg-nova-100 text-nova-700" : "bg-slate-100 text-ink-muted"}`}>{n + 1}</button>))}
      </nav>

      <section className="card p-6" aria-labelledby="q-h">
        <div className="flex flex-wrap items-center gap-2 text-xs"><Badge tone="neutral">{q.topic_name ?? "General"}</Badge><Badge tone="indigo">{q.difficulty}</Badge></div>
        <h2 id="q-h" className="mt-3 whitespace-pre-wrap text-lg font-medium leading-snug">{q.text}</h2>
        <div className="mt-5">
          {q.question_type === "mcq" && (
            <div role="radiogroup" aria-labelledby="q-h" className="space-y-2">
              {q.options?.map((o) => (
                <button key={o.id} type="button" role="radio" aria-checked={answers[q.id] === o.id} onClick={() => set(o.id)}
                  className={`flex w-full items-center gap-3 rounded-ctl border px-4 py-3 text-left ${answers[q.id] === o.id ? "border-nova-600 bg-nova-50" : "border-line hover:border-slate-300"}`}>
                  <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border text-xs font-semibold ${answers[q.id] === o.id ? "border-nova-600 bg-nova-600 text-white" : "border-slate-300"}`}>{o.id.toUpperCase()}</span>{o.text}</button>))}
            </div>)}
          {q.question_type === "short_answer" && <><label htmlFor="ans" className="sr-only">Your answer</label><textarea id="ans" rows={3} maxLength={2000} value={answers[q.id] ?? ""} onChange={(e) => set(e.target.value)} className="input resize-none" placeholder="Type your answer" /></>}
          {q.question_type === "numerical" && <div className="flex items-center gap-2"><label htmlFor="ans" className="sr-only">Your numerical answer</label><input id="ans" inputMode="decimal" value={answers[q.id] ?? ""} onChange={(e) => set(e.target.value)} className="input !w-48" placeholder="Enter a number" />{q.unit && <span className="text-ink-muted">{q.unit}</span>}</div>}
        </div>
      </section>

      <div className="flex items-center justify-between">
        <Button variant="ghost" icon={<ArrowLeft className="h-4 w-4" />} disabled={i === 0} onClick={() => setI(i - 1)}>Previous</Button>
        {i < qs.length - 1
          ? <Button variant="secondary" onClick={() => setI(i + 1)}>Next<ArrowRight className="h-4 w-4" /></Button>
          : <Button icon={<Send className="h-4 w-4" />} loading={busy} onClick={() => setConfirm(true)}>Finish and submit</Button>}
      </div>
      {i < qs.length - 1 && <div className="text-center"><button className="text-sm text-nova-600 hover:underline" onClick={() => setConfirm(true)}>Submit now</button></div>}

      <Dialog open={confirm} onClose={() => setConfirm(false)} title="Submit your answers?" description={qs.length - answered > 0 ? `${qs.length - answered} question${qs.length - answered === 1 ? " is" : "s are"} unanswered. They score zero and don't change your mastery estimates.` : "You answered every question."}>
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setConfirm(false)}>Keep working</Button><Button loading={busy} onClick={() => void submit()}>Submit</Button></div>
      </Dialog>
    </div>
  );
}
