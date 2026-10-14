import { Bot, CalendarDays, ClipboardCheck, Download, FileUp, Lightbulb, TriangleAlert } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { MasteryPanel } from "@/components/dashboard/MasteryPanel";
import { NextStepCard, nextStep } from "@/components/dashboard/NextStepCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { useAsync } from "@/hooks/useAsync";
import { useAuth } from "@/hooks/useAuth";
import { greeting, timeAgo } from "@/lib/format";
import { api } from "@/services/api";
import type { StudyPlan } from "@/types";

function Stat({ value, label }: { value: number; label: string }) {
  return <div className="px-5 py-4"><div className="text-2xl font-semibold tabular-nums">{value}</div><div className="text-[13px] text-ink-muted">{label}</div></div>;
}

export default function Dashboard() {
  const { user } = useAuth();
  const [scheduleCourse, setScheduleCourse] = useState("");
  const [examDate, setExamDate] = useState("");
  const [hoursPerDay, setHoursPerDay] = useState("1");
  const [studyPlan, setStudyPlan] = useState<StudyPlan | null>(null);
  const [scheduleError, setScheduleError] = useState("");
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const { data, error, loading, reload } = useAsync(async () => {
    const [d, courses] = await Promise.all([api.dashboard(), api.courses()]);
    return { d, courses };
  }, []);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold sm:text-3xl">{greeting()}, {user?.name.split(" ")[0]}</h1>
        <p className="mt-1 text-ink-muted">Here is where your study stands.</p>
      </header>

      {error && <ErrorState message={error.message} onRetry={reload} />}
      {loading && !data && (
        <div className="space-y-4"><Skeleton className="h-40" /><div className="grid gap-4 lg:grid-cols-3"><Skeleton className="h-72 lg:col-span-2" /><Skeleton className="h-72" /></div></div>
      )}

      {data && (() => {
        const { d, courses } = data;
        const createPlan = async (event: FormEvent) => {
          event.preventDefault(); setScheduleError(""); setScheduleBusy(true); setStudyPlan(null);
          try { setStudyPlan(await api.studyPlan(scheduleCourse, examDate, Number(hoursPerDay))); }
          catch (e) { setScheduleError(e instanceof Error ? e.message : "Could not create the study plan."); }
          finally { setScheduleBusy(false); }
        };
        const exportCalendar = () => {
          if (!studyPlan) return;
          const escape = (s: string) => s.replace(/[\\,;]/g, "\\$&").replace(/\r?\n/g, "\\n");
          const events = studyPlan.days.flatMap((day) => day.tasks.map((task, i) => {
            const start = day.date.replace(/-/g, "");
            const next = new Date(`${day.date}T00:00:00`); next.setDate(next.getDate() + 1);
            const end = `${next.getFullYear()}${String(next.getMonth() + 1).padStart(2, "0")}${String(next.getDate()).padStart(2, "0")}`;
            const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
            return `BEGIN:VEVENT\nUID:${day.date}-${task.topic_id}-${i}@novalearn\nDTSTAMP:${stamp}\nDTSTART;VALUE=DATE:${start}\nDTEND;VALUE=DATE:${end}\nSUMMARY:${escape(`NOVA study: ${task.topic_name}`)}\nDESCRIPTION:${escape(`${task.minutes} minutes. ${task.reason} ${studyPlan.formula}`)}\nEND:VEVENT`;
          }));
          const blob = new Blob([`BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//NOVA Learn AI//Study Plan//EN\n${events.join("\n")}\nEND:VCALENDAR`], { type: "text/calendar;charset=utf-8" });
          const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "nova-study-plan.ics"; a.click(); URL.revokeObjectURL(url);
        };
        return (
          <>
            <NextStepCard step={nextStep(d, courses)} />

            <div className="card grid grid-cols-2 divide-x divide-line sm:grid-cols-4" aria-label="Library summary">
              <Stat value={d.course_count} label={d.course_count === 1 ? "Course" : "Courses"} />
              <Stat value={d.document_count} label={d.document_count === 1 ? "File uploaded" : "Files uploaded"} />
              <Stat value={d.indexed_document_count} label="Files indexed" />
              <Stat value={d.topic_count} label="Topics found" />
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
              <div className="space-y-6 lg:col-span-2">
                <MasteryPanel mastery={d.mastery} />

                <section className="card p-6">
                  <h2 className="text-base font-semibold">Recent assessments</h2>
                  {d.recent_assessments.length === 0 ? (
                    <EmptyState icon={<ClipboardCheck className="h-5 w-5" />} title="No assessments taken">Quizzes and mock exams appear here with their scores.</EmptyState>
                  ) : (
                    <ul className="mt-3 divide-y divide-line">
                      {d.recent_assessments.map((a) => (
                        <li key={a.attempt_id} className="flex items-center justify-between py-3 text-sm">
                          <span>{courses.find((c) => c.id === a.course_id)?.title ?? "Course"}</span>
                          <span className="flex items-center gap-3"><Badge tone="indigo">{a.score}/{a.max_score}</Badge><span className="text-ink-muted">{timeAgo(a.submitted_at)}</span></span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>

              <div className="space-y-6">
                <section className="card p-6">
                  <h2 className="flex items-center gap-2 text-base font-semibold"><TriangleAlert className="h-4 w-4 text-warn" aria-hidden />Needs attention</h2>
                  {d.weak_topics.length === 0
                    ? <p className="mt-2 text-sm text-ink-muted">No weak topics identified yet. This list is built from quiz results, not guessed.</p>
                    : <ul className="mt-3 space-y-2">{d.weak_topics.map((t) => (
                        <li key={t.topic_id} className="flex items-center justify-between text-sm"><span>{t.topic_name}</span><Badge tone="warn">{Math.round(t.mastery * 100)}% est.</Badge></li>))}</ul>}
                </section>

                <section className="card p-6">
                  <h2 className="flex items-center gap-2 text-base font-semibold"><Lightbulb className="h-4 w-4 text-nova-600" aria-hidden />Revision recommendations</h2>
                  {d.recommendations.length === 0
                    ? <p className="mt-2 text-sm text-ink-muted">Recommendations are based on your performance, so they start after your first quiz.</p>
                    : <ul className="mt-3 space-y-3">{d.recommendations.map((r) => <li key={r.id} className="text-sm text-ink-soft">{r.reason}</li>)}</ul>}
                </section>

                <section className="card p-6">
                  <h2 className="text-base font-semibold">Upcoming revision</h2>
                  {d.upcoming_revisions.length === 0
                    ? <p className="mt-2 text-sm text-ink-muted">Revision dates are scheduled once a topic reaches 75% or more.</p>
                    : <ul className="mt-3 space-y-2">{d.upcoming_revisions.map((r) => (
                        <li key={r.id} className="flex items-center justify-between gap-2 text-sm"><Link to={`/courses/${r.course_id}/assessments`} className="truncate hover:underline">{r.topic_name}</Link>
                          <Badge tone={r.is_due ? "warn" : "neutral"}>{r.is_due ? "Due now" : new Date(r.due_at).toLocaleDateString()}</Badge></li>))}</ul>}
                </section>

                <section className="card p-6">
                  <h2 className="flex items-center gap-2 text-base font-semibold"><CalendarDays className="h-4 w-4 text-nova-600" aria-hidden />Exam study plan</h2>
                  <p className="mt-2 text-sm text-ink-muted">Plan 25-minute sessions around topic mastery estimates and an explicit decay heuristic. Studying does not change your mastery estimate.</p>
                  <form className="mt-4 space-y-3" onSubmit={createPlan}>
                    <label className="block text-sm">Course<select className="input mt-1" required value={scheduleCourse} onChange={(e) => setScheduleCourse(e.target.value)}><option value="">Choose a course</option>{courses.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}</select></label>
                    <label className="block text-sm">Exam date<input className="input mt-1" type="date" required min={new Date().toISOString().slice(0, 10)} value={examDate} onChange={(e) => setExamDate(e.target.value)} /></label>
                    <label className="block text-sm">Available hours per day<input className="input mt-1" type="number" required min="0.5" max="16" step="0.5" value={hoursPerDay} onChange={(e) => setHoursPerDay(e.target.value)} /></label>
                    {scheduleError && <p role="alert" className="text-sm text-bad">{scheduleError}</p>}
                    <Button type="submit" className="w-full" loading={scheduleBusy} disabled={!courses.length}>Build plan</Button>
                  </form>
                  {studyPlan && <div className="mt-4 border-t border-line pt-4">
                    <div className="flex items-center justify-between gap-2"><p className="text-sm font-medium">{studyPlan.days.length} days · {studyPlan.days.reduce((n, day) => n + day.tasks.length, 0)} sessions</p><button onClick={exportCalendar} className="inline-flex items-center gap-1 text-sm text-nova-700 hover:underline"><Download className="h-4 w-4" aria-hidden />Export .ics</button></div>
                    <p className="mt-1 text-xs text-ink-muted">Formula: {studyPlan.formula}. Estimates are planning signals, not observed recall.</p>
                    <ul className="mt-3 max-h-64 space-y-2 overflow-auto text-sm">{studyPlan.days.map((day) => <li key={day.date}><span className="font-medium">{new Date(`${day.date}T00:00:00`).toLocaleDateString()}</span>{day.tasks.length ? day.tasks.map((task) => <div key={task.topic_id} className="ml-3 text-ink-soft">{task.topic_name} · {task.minutes} min · estimated recall {Math.round(task.estimated_recall * 100)}%</div>) : <div className="ml-3 text-ink-muted">No topics available for this course.</div>}</li>)}</ul>
                  </div>}
                </section>

                <section className="card p-6">
                  <h2 className="text-base font-semibold">Recent activity</h2>
                  {d.recent_activity.length === 0
                    ? <p className="mt-2 text-sm text-ink-muted">Uploads and quizzes will show up here.</p>
                    : <ul className="mt-3 space-y-3">{d.recent_activity.map((a, i) => (
                        <li key={i} className="flex items-start gap-3 text-sm">
                          <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-nova-50 text-nova-600">{a.kind === "upload" ? <FileUp className="h-3.5 w-3.5" /> : <ClipboardCheck className="h-3.5 w-3.5" />}</span>
                          <div className="min-w-0"><div className="truncate">{a.label}</div><div className="text-xs text-ink-muted">{timeAgo(a.at)}</div></div>
                        </li>))}</ul>}
                </section>

                <section className="card p-6">
                  <h2 className="flex items-center gap-2 text-base font-semibold"><Bot className="h-4 w-4 text-violet" aria-hidden />AI tutor</h2>
                  {(() => {
                    const ready = courses.find((c) => (c.status_counts.indexed ?? 0) > 0);
                    return ready
                      ? <p className="mt-2 text-sm text-ink-muted">Ask about <Link to={`/courses/${ready.id}/tutor`} className="font-medium text-nova-600 hover:underline">{ready.title}</Link>. Answers cite the page, slide or video moment they come from.</p>
                      : <p className="mt-2 text-sm text-ink-muted">The tutor answers only from indexed course material. Upload a file to a <Link to="/courses" className="font-medium text-nova-600 hover:underline">course</Link> to get started.</p>;
                  })()}
                </section>
              </div>
            </div>
          </>
        );
      })()}
    </div>
  );
}
