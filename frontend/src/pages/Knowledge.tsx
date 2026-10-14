import { ChevronRight, Network, Pencil, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { CapabilityNote } from "@/components/CapabilityNote";
import { ConceptMap } from "@/components/source/ConceptMap";
import { FigurePreview, SourceViewer, locationLabel } from "@/components/source/SourceViewer";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { EmptyState, ErrorState, ProgressBar, Skeleton } from "@/components/ui/Feedback";
import { useAsync } from "@/hooks/useAsync";
import { useToast } from "@/hooks/useToast";
import { plural } from "@/lib/format";
import { ApiError, api } from "@/services/api";
import type { Citation, Topic } from "@/types";

const SRC_LABEL: Record<string, string> = { pdf: "PDF", pptx: "Slides", video: "Video", transcript: "Transcript", image: "Image" };

function TopicForm({ open, title, initial, topics, withParent, onClose, onSubmit }: {
  open: boolean; title: string; initial?: { name: string; description: string }; topics: Topic[]; withParent?: boolean;
  onClose: () => void; onSubmit: (v: { name: string; description: string; parent_id: string | null }) => Promise<void>;
}) {
  const [name, setName] = useState(""); const [description, setDescription] = useState(""); const [parent, setParent] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setName(initial?.name ?? ""); setDescription(initial?.description ?? ""); setParent(""); } }, [open, initial]);
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true);
    try { await onSubmit({ name: name.trim(), description: description.trim(), parent_id: parent || null }); onClose(); } finally { setBusy(false); }
  }
  return (
    <Dialog open={open} onClose={onClose} title={title}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required />
        <div><label htmlFor="td" className="mb-1.5 block text-sm font-medium text-ink-soft">Description</label>
          <textarea id="td" value={description} onChange={(e) => setDescription(e.target.value)} rows={3} maxLength={400} className="input resize-none" /></div>
        {withParent && <div><label htmlFor="tp" className="mb-1.5 block text-sm font-medium text-ink-soft">Part of</label>
          <select id="tp" value={parent} onChange={(e) => setParent(e.target.value)} className="input"><option value="">Top-level topic</option>
            {topics.filter((t) => !t.parent_id).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></div>}
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy} disabled={!name.trim()}>Save</Button></div>
      </form>
    </Dialog>
  );
}

function SourceRow({ c, topics, currentTopic, onMoved }: { c: Citation; topics: Topic[]; currentTopic: string; onMoved: () => void }) {
  const [open, setOpen] = useState(false);
  const toast = useToast();
  return (
    <li className="rounded-ctl border border-line bg-white p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{c.filename}</span><Badge tone="indigo">{locationLabel(c)}</Badge>
        {c.ai_generated && <Badge tone="warn">AI-written</Badge>}
        <button className="ml-auto text-sm font-medium text-nova-600 hover:underline" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Hide" : "Open source"}</button>
      </div>
      {c.figure_ref && c.source_type !== "image" && <div className="mt-2"><FigurePreview citation={c} compact /></div>}
      <p className="mt-1.5 text-sm text-ink-muted">{c.excerpt}</p>
      {open && <div className="mt-3 border-t border-line pt-3"><SourceViewer citation={c} /></div>}
      <label className="mt-2 flex items-center gap-2 text-xs text-ink-muted">Wrong topic? Move to
        <select className="input !w-auto !py-1 !text-xs" value="" onChange={(e) => e.target.value && api.moveChunk(c.chunk_id, e.target.value).then(() => { toast.success("Moved. Rebuilds will keep this."); onMoved(); }).catch((x) => toast.error(x instanceof ApiError ? x.message : "Couldn't move."))}>
          <option value="">Choose…</option>{topics.filter((t) => t.id !== currentTopic).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
    </li>
  );
}

export default function Knowledge() {
  const { id = "" } = useParams();
  const toast = useToast();
  const course = useAsync(() => api.course(id), [id]);
  const topics = useAsync(() => api.topics(id), [id]);
  const [sel, setSel] = useState<string | null>(null);
  const [view, setView] = useState<"list" | "map">("list");
  const [dialog, setDialog] = useState<"edit" | "add" | "rebuild" | "delete" | null>(null);
  const [rebuilding, setRebuilding] = useState(false);

  const list = topics.data ?? [];
  const selected = list.find((t) => t.id === sel) ?? list.find((t) => !t.parent_id) ?? null;
  const sources = useAsync(() => (selected ? api.topicSources(selected.id) : Promise.resolve([] as Citation[])), [selected?.id, topics.data]);
  const total = list.filter((t) => !t.parent_id).reduce((n, t) => n + t.chunk_count, 0) || 1;
  const fail = (m: string) => (e: unknown) => { toast.error(e instanceof ApiError ? e.message : m); };

  async function rebuild() {
    setRebuilding(true);
    try { const r = await api.rebuildTopics(id); toast.success(`Rebuilt: ${plural(r.topics, "topic")} (${r.method === "llm" ? "language model" : "automatic grouping"}).`); await topics.reload(); }
    catch (e) { fail("Couldn't rebuild topics.")(e); } finally { setRebuilding(false); setDialog(null); }
  }

  if (course.error) return <ErrorState message={course.error.message} onRetry={course.reload} />;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to={`/courses/${id}`} className="text-sm text-ink-muted hover:text-ink">← {course.data?.title ?? "Course"}</Link>
          <h1 className="text-2xl font-semibold sm:text-3xl">Knowledge explorer</h1>
          <p className="mt-1 text-ink-muted">Topics found in your material, with where each one comes from.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <div className="inline-flex rounded-ctl border border-line bg-white p-1" role="group" aria-label="View">
            {(["list", "map"] as const).map((v) => <button key={v} onClick={() => setView(v)} aria-pressed={view === v} className={`rounded-lg px-3 py-1.5 text-sm font-medium ${view === v ? "bg-nova-600 text-white" : "text-ink-soft"}`}>{v === "list" ? "List" : "Map"}</button>)}
          </div>
          <Button variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => setDialog("add")}>Add topic</Button>
          <Button variant="secondary" icon={<RefreshCw className="h-4 w-4" />} onClick={() => setDialog("rebuild")} disabled={list.length === 0}>Rebuild</Button>
        </div>
      </div>

      <CapabilityNote />
      <p className="rounded-ctl bg-slate-100 px-4 py-3 text-sm text-ink-soft">Topics are grouped automatically, so names are suggestions. Rename a topic or move a passage to correct it; your edits are kept when topics are rebuilt.</p>

      {topics.error && <ErrorState message={topics.error.message} onRetry={topics.reload} />}
      {topics.loading && !topics.data && <div className="grid gap-4 lg:grid-cols-[320px_1fr]"><Skeleton className="h-80" /><Skeleton className="h-80" /></div>}
      {topics.data && list.length === 0 && (
        <div className="card"><EmptyState icon={<Network className="h-5 w-5" />} title="No topics yet" action={<Link to={`/courses/${id}`}><Button>Go to course material</Button></Link>}>Topics appear after your files finish processing.</EmptyState></div>
      )}

      {selected && (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
          <section className={`card p-3 ${view === "map" ? "lg:col-span-2" : ""}`} aria-label="Topics">
            {view === "map" ? <ConceptMap topics={list} selectedId={selected.id} onSelect={setSel} /> : (
              <ul className="space-y-1">
                {list.filter((t) => !t.parent_id).map((t) => (
                  <li key={t.id}>
                    <button onClick={() => setSel(t.id)} aria-current={selected.id === t.id} className={`w-full rounded-ctl px-3 py-2.5 text-left ${selected.id === t.id ? "bg-nova-50" : "hover:bg-slate-50"}`}>
                      <div className="flex items-center gap-2"><span className="flex-1 truncate font-medium">{t.name}</span>{t.origin === "user" && <Badge tone="indigo">Yours</Badge>}<ChevronRight className="h-4 w-4 text-ink-muted" aria-hidden /></div>
                      <div className="mt-2"><ProgressBar value={t.chunk_count / total} /></div>
                      <div className="mt-1 text-xs text-ink-muted">{plural(t.chunk_count, "passage")} · {Math.round((t.chunk_count / total) * 100)}% of the material</div>
                    </button>
                    {list.filter((s) => s.parent_id === t.id).map((s) => (
                      <button key={s.id} onClick={() => setSel(s.id)} className={`ml-5 mt-0.5 block w-[calc(100%-1.25rem)] rounded-ctl px-3 py-1.5 text-left text-sm ${selected.id === s.id ? "bg-nova-50" : "hover:bg-slate-50"}`}>{s.name}</button>))}
                  </li>))}
              </ul>)}
          </section>

          <section className="card min-w-0 p-6" aria-label="Topic details">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0"><h2 className="break-words text-xl font-semibold">{selected.name}</h2>
                <p className="mt-1 text-ink-muted">{selected.description || "No description yet."}</p></div>
              <div className="flex gap-2"><Button size="sm" variant="secondary" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setDialog("edit")}>Edit</Button>
                <Button size="sm" variant="secondary" className="text-bad" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setDialog("delete")}>Delete</Button></div>
            </div>

            <dl className="mt-5 grid gap-4 sm:grid-cols-2">
              <div><dt className="text-sm font-medium text-ink-soft">Where it comes from</dt>
                <dd className="mt-2 flex flex-wrap gap-2">{Object.entries(selected.source_counts).map(([k, n]) => <Badge key={k} tone="cyan">{SRC_LABEL[k] ?? k}: {plural(n, "passage")}</Badge>)}</dd>
                <dd className="mt-2 space-y-1 text-sm text-ink-muted">{selected.documents.map((d) => <div key={d.id} className="truncate">{d.filename} ({d.chunks})</div>)}</dd></div>
              <div><dt className="text-sm font-medium text-ink-soft">Your mastery</dt>
                <dd className="mt-2 text-sm text-ink-muted">{selected.mastery == null ? "No learner evidence yet. Take the diagnostic or ask for simpler help on this topic." : `${Math.round(selected.mastery * 100)}% (estimate from ${selected.mastery_evidence} evidence event${selected.mastery_evidence === 1 ? "" : "s"}${selected.mastery_evidence < 3 ? ", early" : ""})`}</dd></div>
            </dl>

            <div className="mt-6">
              <h3 className="text-sm font-medium text-ink-soft">Prerequisites</h3>
              {selected.prerequisites.length === 0 && <p className="mt-1.5 text-sm text-ink-muted">None recorded. Prerequisite links come from a language model or from you; they are never guessed from similarity.</p>}
              <div className="mt-2 flex flex-wrap gap-2">
                {selected.prerequisites.map((p) => (
                  <span key={p.id} className="inline-flex items-center gap-1.5 rounded-full bg-violet-soft py-1 pl-3 pr-1.5 text-sm text-violet">
                    <button onClick={() => setSel(p.id)} className="hover:underline">{p.name}</button>
                    <button aria-label={`Remove prerequisite ${p.name}`} onClick={() => api.removePrerequisite(selected.id, p.id).then(topics.reload).catch(fail("Couldn't remove."))} className="rounded-full p-0.5 hover:bg-white"><X className="h-3.5 w-3.5" /></button></span>))}
                <select aria-label="Add prerequisite" className="input !w-auto !py-1 !text-sm" value="" onChange={(e) => e.target.value && api.addPrerequisite(selected.id, e.target.value).then(() => { toast.success("Prerequisite added."); return topics.reload(); }).catch(fail("Couldn't add."))}>
                  <option value="">Add prerequisite…</option>
                  {list.filter((t) => !t.parent_id && t.id !== selected.id && !selected.prerequisites.some((p) => p.id === t.id)).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
              </div>
            </div>

            <div className="mt-6">
              <h3 className="text-sm font-medium text-ink-soft">Source passages</h3>
              {sources.loading && !sources.data && <Skeleton className="mt-2 h-20" />}
              {sources.data?.length === 0 && <p className="mt-1.5 text-sm text-ink-muted">No passages are assigned to this topic.</p>}
              <ul className="mt-2 space-y-2">{sources.data?.map((c) => <SourceRow key={c.chunk_id} c={c} topics={list} currentTopic={selected.id} onMoved={() => { void topics.reload(); }} />)}</ul>
            </div>
          </section>
        </div>
      )}

      <TopicForm open={dialog === "add"} title="Add a topic" topics={list} withParent onClose={() => setDialog(null)}
        onSubmit={(v) => api.createTopic(id, v).then((t) => { toast.success("Topic added."); setSel(t.id); return topics.reload(); }).catch((e) => { fail("Couldn't add the topic.")(e); throw e; })} />
      <TopicForm open={dialog === "edit"} title="Edit topic" initial={selected ? { name: selected.name, description: selected.description } : undefined} topics={list} onClose={() => setDialog(null)}
        onSubmit={(v) => api.patchTopic(selected!.id, { name: v.name, description: v.description }).then(() => { toast.success("Topic updated."); return topics.reload(); }).catch((e) => { fail("Couldn't save.")(e); throw e; })} />
      <Dialog open={dialog === "rebuild"} onClose={() => setDialog(null)} title="Rebuild automatic topics?" description="Topics are regenerated from all indexed material. Topics you created or edited, and passages you moved, are kept.">
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setDialog(null)}>Cancel</Button><Button loading={rebuilding} onClick={rebuild}>Rebuild</Button></div></Dialog>
      <Dialog open={dialog === "delete"} onClose={() => setDialog(null)} title="Delete this topic?" description="Its passages stay in your course but become unassigned. Subtopics are deleted too.">
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setDialog(null)}>Cancel</Button>
          <Button variant="danger" onClick={() => api.deleteTopic(selected!.id).then(() => { toast.success("Topic deleted."); setSel(null); setDialog(null); return topics.reload(); }).catch(fail("Couldn't delete."))}>Delete topic</Button></div></Dialog>
    </div>
  );
}
