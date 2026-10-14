import { useMemo, useState } from "react";
import { BookOpenCheck, Eye, EyeOff } from "lucide-react";

import { SourceViewer } from "@/components/source/SourceViewer";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { useAsync } from "@/hooks/useAsync";
import { api } from "@/services/api";

export default function RevisionCards() {
  const courses = useAsync(() => api.courses(), []);
  const [courseId, setCourseId] = useState("");
  const selectedId = courseId || courses.data?.[0]?.id || "";
  const cards = useAsync(() => selectedId ? api.revisionCards(selectedId) : Promise.resolve([]), [selectedId]);
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const selectedCourse = useMemo(() => courses.data?.find((c) => c.id === selectedId), [courses.data, selectedId]);

  if (courses.error) return <ErrorState message={courses.error.message} onRetry={courses.reload} />;
  return <div className="space-y-6">
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div><p className="flex items-center gap-2 text-sm text-nova-600"><BookOpenCheck className="h-4 w-4" aria-hidden />Source grounded practice</p>
        <h1 className="mt-1 text-2xl font-semibold sm:text-3xl">Revision cards</h1>
        <p className="mt-1 text-sm text-ink-muted">Verified questions from topics with low mastery estimates. Answers appear when you choose to reveal them.</p></div>
      {courses.data && courses.data.length > 0 && <label className="text-sm">Course
        <select className="input mt-1 block min-w-48" value={selectedId} onChange={(e) => { setCourseId(e.target.value); setRevealed({}); }}>
          {courses.data.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
        </select></label>}
    </header>
    {courses.loading && !courses.data ? <Skeleton className="h-48" /> : !courses.data?.length ?
      <EmptyState icon={<BookOpenCheck className="h-5 w-5" />} title="No courses yet">Create a course and add learning materials to get started.</EmptyState> : cards.error ?
      <ErrorState message={cards.error.message} onRetry={cards.reload} /> : cards.loading && !cards.data ? <Skeleton className="h-48" /> :
      cards.data?.length ? <div className="grid gap-4 md:grid-cols-2">{cards.data.map((card) => <article key={card.id} className="card p-5">
        <div className="text-xs font-medium uppercase tracking-wide text-nova-600">{card.topic}</div>
        <h2 className="mt-3 text-base font-semibold">{card.front}</h2>
        <button type="button" className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-nova-600 hover:text-nova-800" aria-expanded={!!revealed[card.id]}
          onClick={() => setRevealed((old) => ({ ...old, [card.id]: !old[card.id] }))}>
          {revealed[card.id] ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}{revealed[card.id] ? "Hide answer" : "Reveal answer"}</button>
        {revealed[card.id] && <div className="mt-3 rounded-lg bg-slate-50 p-4 text-sm"><p className="font-medium">{card.answer}</p><p className="mt-2 text-ink-muted">{card.explanation}</p></div>}
        <div className="mt-4 border-t border-line pt-3"><p className="text-xs font-medium text-ink-muted">Sources</p>
          <ul className="mt-1 space-y-2">{card.citations.map((cite) => <li key={cite.chunk_id} className="text-xs text-ink-muted"><details>
            <summary className="cursor-pointer text-nova-700 hover:underline">{cite.filename}{cite.page != null ? ` · p. ${cite.page}` : cite.slide != null ? ` · slide ${cite.slide}` : cite.start_seconds != null ? ` · ${Math.floor(cite.start_seconds)}s` : ""} — open source</summary>
            <div className="mt-2"><SourceViewer citation={cite} /></div>
          </details></li>)}</ul></div>
      </article>)}</div> : <EmptyState icon={<BookOpenCheck className="h-5 w-5" />} title="No revision cards available">Cards appear when a topic has a low mastery estimate and verified questions with source citations. No cards are generated to fill gaps.</EmptyState>}
    {selectedCourse && <p className="text-xs text-ink-muted">{selectedCourse.title} · Only verified questions with stored source material are shown.</p>}
  </div>;
}
