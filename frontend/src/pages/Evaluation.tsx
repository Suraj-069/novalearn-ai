import { FlaskConical, RefreshCw, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { useAsync } from "@/hooks/useAsync";
import { useToast } from "@/hooks/useToast";
import { ApiError, api } from "@/services/api";
import type { EvaluationMetric, EvaluationRun } from "@/types";

type RetrievalCase = { question: string; reference_answer: string | null; relevant_chunk_ids: string[]; should_refuse: boolean };
const METRIC_LABELS: Record<string, string> = {
  context_precision: "Context precision", context_recall: "Context recall", faithfulness: "Faithfulness",
  answer_relevancy: "Answer relevancy", refusal_accuracy: "Refusal accuracy",
  citation_accuracy: "Citation accuracy", hit_at_k: "Retrieval hit@k", mrr: "Mean reciprocal rank",
  false_refusal_rate: "False-refusal rate", false_acceptance_rate: "False-acceptance rate",
  evaluated_cases: "Cases evaluated", simulated_mastery_gain: "Simulated mastery change",
  random_baseline_mastery_gain: "Random baseline mastery change", mastery_gain_delta: "Adaptive gain vs baseline",
  question_repetition_rate: "Adaptive repetition rate", baseline_repetition_rate: "Random baseline repetition rate",
  adaptive_estimate_error: "Adaptive estimate error", random_baseline_estimate_error: "Baseline estimate error",
  adaptive_topic_coverage: "Adaptive topic coverage", random_baseline_topic_coverage: "Baseline topic coverage",
  adaptive_weak_topic_selection_rate: "Adaptive weak-topic selection",
};

function metricValue(metric: EvaluationMetric): string {
  if (!metric.available || metric.value == null) return "Not computed";
  if (["simulated_mastery_gain", "random_baseline_mastery_gain", "mastery_gain_delta"].includes(metric.name)) {
    const points = metric.value * 100;
    return `${points > 0 ? "+" : ""}${points.toFixed(1)} percentage points`;
  }
  if (metric.name === "evaluated_cases") return String(metric.value);
  return `${(metric.value * 100).toFixed(1)}%`;
}

function location(source: { page: number | null; slide: number | null; start_seconds: number | null }) {
  if (source.page != null) return `page ${source.page}`;
  if (source.slide != null) return `slide ${source.slide}`;
  if (source.start_seconds != null) return `at ${Math.floor(source.start_seconds)}s`;
  return "location not recorded";
}

type EvaluatedCase = {
  case: number; question: string; category: string | null; should_refuse: boolean;
  answer: string | null; answer_mode: string | null; answer_error: string | null;
  retrieved_chunk_ids: string[]; retrieved_contexts: string[]; retrieved_sources: {
    chunk_id: string; filename: string; page: number | null; slide: number | null;
    start_seconds: number | null; end_seconds: number | null; excerpt: string;
  }[];
  context_precision: number | null; context_recall: number | null; citation_accuracy: number | null;
  faithfulness: number | null; answer_relevancy: number | null; judge_error: string | null;
};

function caseIssues(item: EvaluatedCase): string[] {
  const issues: string[] = [];
  if (item.answer_error) issues.push("Tutor output failed");
  if (item.answer_mode && item.should_refuse !== (item.answer_mode === "unsupported")) issues.push("Refusal label mismatch");
  if (item.context_recall != null && item.context_recall < 1) issues.push("Gold source not fully retrieved");
  if (item.citation_accuracy != null && item.citation_accuracy < 1) issues.push("Citation misses a gold source");
  if (item.faithfulness != null && item.faithfulness < 0.7) issues.push("Low judge faithfulness score");
  if (item.answer_relevancy != null && item.answer_relevancy < 0.7) issues.push("Low judge answer-relevancy score");
  if (item.judge_error) issues.push("Judge could not score this answer");
  return issues;
}

function RunCard({ run }: { run: EvaluationRun }) {
  const detailsMetric = run.metrics.find((m) => m.name === "case_details");
  const cases = (detailsMetric?.details.cases ?? []) as EvaluatedCase[];
  const categoryCases = cases.filter((item) => item.category);
  const categories = categoryCases.reduce<Record<string, EvaluatedCase[]>>((groups, item) => {
    const key = item.category ?? "Uncategorized";
    (groups[key] ??= []).push(item);
    return groups;
  }, {});
  const flaggedCases = cases.map((item) => ({ item, issues: caseIssues(item) }))
    .filter((entry) => entry.issues.length > 0)
    .sort((a, b) => b.issues.length - a.issues.length || a.item.case - b.item.case)
    .slice(0, 5);
  const arms = run.metrics.find((m) => m.name === "simulated_mastery_gain")?.details.arms as Record<string, {
    mastery_gain_mean: number; mastery_gain_stddev: number; estimate_error_mean: number;
    repetition_rate_mean: number; topic_coverage_mean: number; weak_topic_selection_rate_mean: number; sample_size: number;
  }> | undefined;

  return (
    <article className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h3 className="font-semibold">{run.kind === "retrieval" ? "Retrieval and grounding" : "Personalization simulation"}</h3>
          <p className="mt-1 text-xs text-ink-muted">{new Date(run.created_at).toLocaleString()} · {run.metrics.find((m) => m.name === "evaluated_cases")?.sample_size ?? run.metrics.find((m) => m.name === "simulated_mastery_gain")?.sample_size ?? 0} samples</p></div>
        <Badge tone={run.status === "completed" ? "ok" : run.status === "failed" ? "bad" : "warn"}>{run.status}</Badge>
      </div>
      {run.kind === "retrieval" && <p className="mt-2 text-xs text-ink-muted">Answer model: {String(run.config.answer_model ?? "not recorded")} · Judge: {String(run.config.judge_model ?? "not recorded")}</p>}
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {run.metrics.filter((m) => m.name !== "case_details").map((metric) => (
          <div key={metric.name} className="rounded-ctl bg-slate-50 p-3">
            <div className="text-xs text-ink-muted">{METRIC_LABELS[metric.name] ?? metric.name}</div>
            <div className="mt-1 font-semibold">{metricValue(metric)}</div>
            {metric.available && metric.sample_size != null && <div className="mt-1 text-xs text-ink-muted">n = {metric.sample_size}</div>}
            {!metric.available && metric.unavailable_reason && <div className="mt-1 text-xs text-ink-muted">{metric.unavailable_reason}</div>}
          </div>
        ))}
      </div>
      {run.notes && <p className="mt-4 rounded-ctl bg-amber-50 px-3 py-2.5 text-sm text-amber-900">{run.notes}</p>}
      {arms && <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[660px] text-left text-sm"><thead className="text-xs text-ink-muted"><tr><th className="py-2 pr-3">Selection policy</th><th className="py-2 pr-3">Mean synthetic gain ± SD</th><th className="py-2 pr-3">Estimate error</th><th className="py-2 pr-3">Repeated</th><th className="py-2 pr-3">Topic coverage</th><th className="py-2 pr-3">Weak topics selected</th></tr></thead>
          <tbody>{Object.entries(arms).map(([name, p]) => <tr key={name} className="border-t border-line"><td className="py-2 pr-3 font-medium capitalize">{name === "random" ? "Random baseline" : "Adaptive"} (n={p.sample_size})</td><td className="py-2 pr-3">{(p.mastery_gain_mean * 100).toFixed(1)} ± {(p.mastery_gain_stddev * 100).toFixed(1)} pp</td><td className="py-2 pr-3">{(p.estimate_error_mean * 100).toFixed(1)}%</td><td className="py-2 pr-3">{(p.repetition_rate_mean * 100).toFixed(1)}%</td><td className="py-2 pr-3">{(p.topic_coverage_mean * 100).toFixed(1)}%</td><td className="py-2 pr-3">{(p.weak_topic_selection_rate_mean * 100).toFixed(1)}%</td></tr>)}</tbody>
        </table>
      </div>}
      {cases.length > 0 && <details className="mt-4">
        <summary className="cursor-pointer text-sm font-medium text-nova-700">View case outputs</summary>
        <ul className="mt-2 space-y-2">{cases.map((c) => <li key={c.case} className="rounded-ctl border border-line p-3 text-sm">
          <p className="font-medium">{c.case}. {c.question}</p><p className="mt-1 text-ink-muted">Mode: {c.answer_mode ?? "unavailable"}</p>
          {c.answer && <p className="mt-2 whitespace-pre-wrap">{c.answer}</p>}
          {c.judge_error && <p className="mt-1 text-warn">Judge unavailable for this case: {c.judge_error}</p>}
          {c.retrieved_sources.length > 0 ? <ul className="mt-2 space-y-1 text-xs text-ink-muted">{c.retrieved_sources.map((source) => <li key={source.chunk_id} className="rounded-ctl bg-slate-50 p-2">
            <span className="font-medium">{source.filename}</span> · {location(source)} · chunk <code className="break-all">{source.chunk_id}</code>
            <p className="mt-1">{source.excerpt}</p>
          </li>)}</ul> : <p className="mt-2 text-xs text-ink-muted">No source chunks retrieved.</p>}
        </li>)}</ul>
      </details>}
      {Object.keys(categories).length > 0 && <section className="mt-4">
        <h4 className="text-sm font-semibold">Per-category results</h4>
        <div className="mt-2 overflow-x-auto"><table className="w-full min-w-[520px] text-left text-xs"><thead className="text-ink-muted"><tr><th className="py-2 pr-3">Category</th><th className="py-2 pr-3">Cases</th><th className="py-2 pr-3">Mean context recall</th><th className="py-2 pr-3">Refusal accuracy</th></tr></thead>
          <tbody>{Object.entries(categories).map(([category, items]) => {
            const recalled = items.filter((item) => item.context_recall != null);
            const recall = recalled.length ? recalled.reduce((sum, item) => sum + (item.context_recall ?? 0), 0) / recalled.length : null;
            const judged = items.filter((item) => item.answer_mode != null);
            const refusalAccuracy = judged.length ? judged.filter((item) => item.should_refuse === (item.answer_mode === "unsupported")).length / judged.length : null;
            return <tr key={category} className="border-t border-line"><td className="py-2 pr-3">{category}</td><td className="py-2 pr-3">{items.length}</td><td className="py-2 pr-3">{recall == null ? "Not computed" : `${(recall * 100).toFixed(1)}%`}</td><td className="py-2 pr-3">{refusalAccuracy == null ? "Not computed" : `${(refusalAccuracy * 100).toFixed(1)}%`}</td></tr>;
          })}</tbody>
        </table></div>
      </section>}
      {run.kind === "retrieval" && cases.length > 0 && <section className="mt-4">
        <h4 className="text-sm font-semibold">Cases to review</h4>
        {flaggedCases.length === 0 ? <p className="mt-1 text-xs text-ink-muted">No failures were flagged by the available per-case metrics.</p> : <ul className="mt-2 space-y-2">{flaggedCases.map(({ item, issues }) => <li key={item.case} className="rounded-ctl border border-amber-200 bg-amber-50 p-3 text-sm">
          <p className="font-medium">{item.case}. {item.question}</p><p className="mt-1 text-xs text-amber-900">{issues.join(" · ")}</p>
          {item.retrieved_sources.length > 0 && <p className="mt-1 text-xs text-ink-muted">Sources retrieved: {item.retrieved_sources.map((source) => `${source.filename}, ${location(source)}`).join("; ")}</p>}
        </li>)}</ul>}
      </section>}
    </article>
  );
}

export default function Evaluation() {
  const { id = "" } = useParams();
  const toast = useToast();
  const course = useAsync(() => api.course(id), [id]);
  const runs = useAsync(() => api.evaluations(id), [id]);
  const [query, setQuery] = useState("");
  const sources = useAsync(() => api.evaluationSources(id, query), [id, query]);
  const [dataset, setDataset] = useState("");
  const [sessions, setSessions] = useState(5);
  const [questionsPerSession, setQuestionsPerSession] = useState(5);
  const [busy, setBusy] = useState<"retrieval" | "simulation" | null>(null);
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "The evaluation could not run.");

  async function submitRetrieval(event: FormEvent) {
    event.preventDefault();
    let parsed: unknown;
    try { parsed = JSON.parse(dataset); }
    catch { toast.error("The test set must be valid JSON."); return; }
    if (!Array.isArray(parsed) || parsed.length === 0) { toast.error("Add at least one test case as a JSON array."); return; }
    setBusy("retrieval");
    try { await api.runRetrievalEvaluation(id, parsed as RetrievalCase[]); setDataset(""); await runs.reload(); toast.success("Retrieval evaluation saved."); }
    catch (e) { fail(e); }
    finally { setBusy(null); }
  }

  async function runSimulation() {
    setBusy("simulation");
    try { await api.runPersonalizationEvaluation(id, { sessions, questions_per_session: questionsPerSession, seed: 17 }); await runs.reload(); toast.success("Personalization simulation saved."); }
    catch (e) { fail(e); }
    finally { setBusy(null); }
  }

  if (course.error) return <ErrorState message={course.error.message} onRetry={course.reload} />;

  return (
    <div className="space-y-6">
      <div><Link to={`/courses/${id}`} className="text-sm text-ink-muted hover:text-ink">â† {course.data?.title ?? "Course"}</Link>
        <h1 className="mt-1 text-2xl font-semibold sm:text-3xl">System evaluation</h1>
        <p className="mt-1 text-ink-muted">Run labeled retrieval checks and seeded learner simulations against this course.</p></div>

      <section className="rounded-card border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-950">
        <h2 className="font-semibold">Metric notes</h2>
        <p className="mt-1">Context precision and recall compare retrieved chunk IDs with the source labels you provide. Faithfulness and answer relevancy use your configured language model as a single rubric judge; they are unavailable when no model is configured and are not an independent evaluation.</p>
        <p className="mt-1">Fixed-seed synthetic profiles compare adaptive topic selection with uniform random selection across repeated runs. Hidden learner response and forgetting parameters are separate from app BKT constants; answers are graded by the app's deterministic grader. Results are not evidence of real learning and do not change your learner history.</p>
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <section className="card p-5">
          <h2 className="text-lg font-semibold">Retrieval and grounded answers</h2>
          <p className="mt-1 text-sm text-ink-muted">Build a small team-labeled test set. Answerable cases need a reference answer and one or more real chunk IDs. Off-material cases should have no source IDs and set <code>should_refuse</code> to true.</p>
          <form onSubmit={submitRetrieval} className="mt-4 space-y-3">
            <label className="block text-sm font-medium" htmlFor="evaluation-cases">Test cases (JSON array)</label>
            <textarea id="evaluation-cases" className="input min-h-52 resize-y font-mono text-xs" value={dataset} onChange={(e) => setDataset(e.target.value)} placeholder={'[\n  {\n    "question": "What does the source say?",\n    "reference_answer": "A human-checked reference answer",\n    "relevant_chunk_ids": ["paste-a-real-chunk-uuid"],\n    "should_refuse": false\n  },\n  {\n    "question": "An off-material question",\n    "reference_answer": null,\n    "relevant_chunk_ids": [],\n    "should_refuse": true\n  }\n]'} />
            <Button type="submit" loading={busy === "retrieval"} disabled={busy !== null || !dataset.trim()} icon={<FlaskConical className="h-4 w-4" />}>Run retrieval evaluation</Button>
          </form>
          <div className="mt-5 border-t border-line pt-4">
            <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium">Real source chunks</h3><span className="text-xs text-ink-muted">{sources.data?.total ?? 0} matching</span></div>
            <label className="relative mt-2 block"><span className="sr-only">Search source text</span><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" aria-hidden /><input className="input pl-9" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search source text" /></label>
            {sources.error && <ErrorState message={sources.error.message} onRetry={sources.reload} />}
            {sources.loading && !sources.data && <Skeleton className="mt-3 h-24" />}
            {sources.data && sources.data.items.length === 0 && <p className="mt-3 text-sm text-ink-muted">No source chunks match. Process course material and search by a distinctive phrase.</p>}
            {sources.data && sources.data.items.length > 0 && <>
              <ul className="mt-3 max-h-80 space-y-2 overflow-y-auto">{sources.data.items.map((source) => <li key={source.chunk_id} className="rounded-ctl border border-line p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs"><span className="font-medium">{source.filename}</span><Badge tone="cyan">{location(source)}</Badge>{source.topic_name && <Badge tone="indigo">{source.topic_name}</Badge>}{source.ai_generated && <Badge tone="warn">AI-written</Badge>}</div>
                <p className="mt-1.5 text-sm text-ink-muted">{source.excerpt}</p>
                <code className="mt-1 block break-all text-[11px] text-ink-soft" title="Copy this real source ID into relevant_chunk_ids">{source.chunk_id}</code>
              </li>)}</ul>
              {sources.data.total > sources.data.items.length && <p className="mt-2 text-xs text-ink-muted">Showing the first {sources.data.items.length} matches. Narrow the search to find other passages.</p>}
            </>}
          </div>
        </section>

        <section className="card p-5">
          <h2 className="text-lg font-semibold">Simulated learner profiles</h2>
          <p className="mt-1 text-sm text-ink-muted">The run replays verified questions already in the question bank, favors lower estimated mastery topics, and tracks when the pool runs out of unseen questions. The default profiles use 30%, 60%, and 85% medium-question skill probabilities.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="text-sm font-medium">Sessions<input className="input mt-1" type="number" min={5} max={12} value={sessions} onChange={(e) => setSessions(Number(e.target.value))} /></label>
            <label className="text-sm font-medium">Questions per session<input className="input mt-1" type="number" min={1} max={20} value={questionsPerSession} onChange={(e) => setQuestionsPerSession(Number(e.target.value))} /></label>
          </div>
          <Button className="mt-4" onClick={runSimulation} loading={busy === "simulation"} disabled={busy !== null} icon={<RefreshCw className="h-4 w-4" />}>Run simulation</Button>
          <p className="mt-3 text-xs text-ink-muted">The simulation runs five seeded repetitions by default. It needs verified questions across course topics; an empty question bank produces unavailable metrics.</p>
        </section>
      </div>

      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3"><h2 className="text-xl font-semibold">Saved evaluation runs</h2><Button size="sm" variant="secondary" onClick={() => void runs.reload()} icon={<RefreshCw className="h-3.5 w-3.5" />}>Refresh</Button></div>
        {runs.error && <ErrorState message={runs.error.message} onRetry={runs.reload} />}
        {runs.loading && !runs.data && <Skeleton className="h-36" />}
        {runs.data && runs.data.length === 0 && <div className="card"><EmptyState icon={<FlaskConical className="h-5 w-5" />} title="No evaluation runs yet">Runs will appear here with their actual sample counts and any metrics the current setup can compute.</EmptyState></div>}
        {runs.data?.map((run) => <RunCard key={run.id} run={run} />)}
      </section>
    </div>
  );
}
