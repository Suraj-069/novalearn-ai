import { BarChart3, CalendarClock, TrendingUp } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { MasteryNote } from "@/components/MasteryNote";
import { Badge } from "@/components/ui/Badge";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { useAsync } from "@/hooks/useAsync";
import { isEarly, masteryTone, MODE_LABEL, pct } from "@/lib/mastery";
import { timeAgo } from "@/lib/format";
import { api } from "@/services/api";
import type { Analytics as A } from "@/types";

const COLORS = ["#4338ca", "#7c3aed", "#0e8aa6", "#b45309", "#047857", "#b42318"];
const STATUS = { strong: "Strong", developing: "Developing", weak: "Needs work", not_assessed: "Not assessed" } as const;

function Panel({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return <section className="card p-6"><h2 className="text-base font-semibold">{title}</h2>{sub && <p className="mt-1 text-sm text-ink-muted">{sub}</p>}<div className="mt-4">{children}</div></section>;
}
const none = (t: string) => <EmptyState icon={<BarChart3 className="h-5 w-5" />} title="No data yet">{t}</EmptyState>;

/** Carry each topic's last known value forward so lines are continuous across answers. */
function timelineSeries(tl: A["timeline"]) {
  const topics = [...new Set(tl.map((t) => t.topic_name))];
  const last: Record<string, number | null> = Object.fromEntries(topics.map((t) => [t, null]));
  return { topics, data: tl.map((e, i) => { last[e.topic_name] = Math.round(e.mastery * 100); return { n: i + 1, ...last }; }) };
}

export default function Analytics() {
  const { id = "" } = useParams();
  const course = useAsync(() => api.course(id), [id]);
  const { data: d, error, loading, reload } = useAsync(() => api.analytics(id), [id]);
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  const tl = d ? timelineSeries(d.timeline) : null;

  return (
    <div className="space-y-6">
      <div><Link to={`/courses/${id}`} className="text-sm text-ink-muted hover:text-ink">← {course.data?.title ?? "Course"}</Link>
        <h1 className="text-2xl font-semibold sm:text-3xl">Learning analytics</h1><div className="mt-1"><MasteryNote text={d?.note} /></div></div>
      {loading && !d && <div className="grid gap-4 md:grid-cols-2"><Skeleton className="h-72" /><Skeleton className="h-72" /></div>}
      {d && (<>
        <div className="grid gap-6 lg:grid-cols-2">
          <Panel title="Topic mastery (estimate)" sub="Based on your answers. Early estimates rest on very few answers.">
            {d.mastery.every((m) => m.mastery == null) ? none("Take a quiz and your estimates appear here.") : (
              <ul className="space-y-3">{d.mastery.map((m) => (
                <li key={m.topic_id} className="flex items-center gap-3 text-sm"><span className="w-40 shrink-0 truncate font-medium" title={m.topic_name}>{m.topic_name}</span>
                  <div className="h-3 flex-1 overflow-hidden rounded-full bg-slate-100" role="img" aria-label={m.mastery == null ? "Not assessed" : `${pct(m.mastery)} estimated`}>
                    {m.mastery != null && <div className={`h-full rounded-full ${m.mastery < 0.4 ? "bg-warn" : m.mastery < 0.75 ? "bg-nova-600" : "bg-ok"}`} style={{ width: `${Math.max(3, m.mastery * 100)}%` }} />}</div>
                  <span className="w-28 shrink-0 text-right"><Badge tone={masteryTone(m.mastery)}>{m.mastery == null ? STATUS.not_assessed : `${pct(m.mastery)}${isEarly(m.evidence) ? " · early" : ""}`}</Badge></span></li>))}</ul>)}
          </Panel>
          <Panel title="Strong and weak topics" sub="Strong: estimate 75% or more. Weak: below 40%.">
            {d.strong.length + d.weak.length === 0 ? <p className="text-sm text-ink-muted">No topic is clearly strong or weak yet.</p> : (
              <div className="grid gap-4 sm:grid-cols-2"><div><h3 className="mb-2 text-sm font-medium text-ok">Strong</h3>{d.strong.length === 0 ? <p className="text-sm text-ink-muted">None yet</p> : d.strong.map((m) => <p key={m.topic_id} className="text-sm">{m.topic_name} <span className="text-ink-muted">{pct(m.mastery!)}</span></p>)}</div>
                <div><h3 className="mb-2 text-sm font-medium text-warn">Needs work</h3>{d.weak.length === 0 ? <p className="text-sm text-ink-muted">None yet</p> : d.weak.map((m) => <p key={m.topic_id} className="text-sm">{m.topic_name} <span className="text-ink-muted">{pct(m.mastery!)}</span></p>)}</div></div>)}
          </Panel>
        </div>

        <Panel title="Mastery over time" sub="Each point is one graded answer. The x-axis counts answers, not days.">
          {!tl || tl.data.length === 0 ? none("This chart fills in as you answer questions.") : (
            <div className="h-72"><ResponsiveContainer><LineChart data={tl.data} margin={{ left: -10, right: 12 }}><CartesianGrid strokeDasharray="3 3" stroke="#e3e6ef" /><XAxis dataKey="n" tick={{ fontSize: 12 }} /><YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 12 }} /><Tooltip formatter={(v: number) => `${v}% (estimate)`} /><Legend />
              {tl.topics.map((t, i) => <Line key={t} type="monotone" dataKey={t} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} connectNulls />)}</LineChart></ResponsiveContainer></div>)}
        </Panel>

        <div className="grid gap-6 lg:grid-cols-2">
          <Panel title="Assessment history" sub="Accuracy of each completed attempt.">
            {d.assessments.length === 0 ? none("Complete an assessment to see it here.") : (<>
              <div className="h-56"><ResponsiveContainer><LineChart data={d.assessments.map((a, i) => ({ n: i + 1, accuracy: Math.round(a.accuracy * 100) }))} margin={{ left: -10, right: 12 }}><CartesianGrid strokeDasharray="3 3" stroke="#e3e6ef" /><XAxis dataKey="n" tick={{ fontSize: 12 }} /><YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 12 }} /><Tooltip formatter={(v: number) => `${v}%`} /><Line dataKey="accuracy" stroke="#4338ca" strokeWidth={2.5} /></LineChart></ResponsiveContainer></div>
              <ul className="mt-3 divide-y divide-line text-sm">{[...d.assessments].reverse().slice(0, 6).map((a) => <li key={a.attempt_id} className="flex items-center justify-between py-2"><span>{MODE_LABEL[a.mode] ?? a.mode} · {timeAgo(a.submitted_at)}</span><Link to={`/attempts/${a.attempt_id}`} className="flex items-center gap-2"><Badge tone="indigo">{a.score}/{a.max_score}</Badge><span className="text-xs font-medium text-nova-600">Review</span></Link></li>)}</ul></>)}
          </Panel>
          <Panel title="Performance by difficulty" sub="Share of answered questions you got fully right.">
            {d.difficulty.every((x) => x.answered === 0) ? none("Answer some questions to see this.") : (
              <div className="h-56"><ResponsiveContainer><BarChart data={d.difficulty.map((x) => ({ name: x.difficulty, accuracy: x.accuracy == null ? 0 : Math.round(x.accuracy * 100), answered: x.answered }))} margin={{ left: -10 }}><CartesianGrid strokeDasharray="3 3" stroke="#e3e6ef" vertical={false} /><XAxis dataKey="name" tick={{ fontSize: 12 }} /><YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 12 }} /><Tooltip formatter={(v: number, _n, p) => [`${v}% of ${p.payload.answered} answered`, "Accuracy"]} /><Bar dataKey="accuracy" radius={[8, 8, 0, 0]}>{d.difficulty.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}</Bar></BarChart></ResponsiveContainer></div>)}
          </Panel>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Panel title="Activity, last 14 days"><div className="h-48"><ResponsiveContainer><BarChart data={d.activity.map((x) => ({ ...x, day: x.date.slice(5) }))} margin={{ left: -20 }}><XAxis dataKey="day" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="answers" name="Answers" fill="#5b50e0" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer></div></Panel>
          <Panel title="Upcoming revision" sub="Spaced repetition: stronger topics come back later.">
            {d.due_revisions.length === 0 ? <p className="flex items-center gap-2 text-sm text-ink-muted"><CalendarClock className="h-4 w-4" aria-hidden />Revision dates appear once a topic reaches 75% or more.</p> :
              <ul className="space-y-3">{d.due_revisions.map((r) => <li key={r.id} className="flex items-center justify-between gap-3 text-sm"><span>{r.topic_name}</span><Badge tone={r.is_due ? "warn" : "neutral"} icon={<TrendingUp className="h-3 w-3" />}>{r.is_due ? "Due now" : `Due ${new Date(r.due_at).toLocaleDateString()}`}</Badge></li>)}</ul>}
          </Panel>
        </div>
      </>)}
    </div>
  );
}
