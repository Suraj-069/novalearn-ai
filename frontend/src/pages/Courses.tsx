import { BookOpen, FileText, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { CourseDialog } from "@/components/CourseDialog";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { useAsync } from "@/hooks/useAsync";
import { useToast } from "@/hooks/useToast";
import { plural, timeAgo } from "@/lib/format";
import { ApiError, api } from "@/services/api";

export default function Courses() {
  const { data: courses, error, loading, reload } = useAsync(() => api.courses(), []);
  const [creating, setCreating] = useState(false);
  const toast = useToast();
  const navigate = useNavigate();

  async function create(v: { title: string; description: string }) {
    try {
      const c = await api.createCourse(v);
      toast.success(`Created “${c.title}”.`);
      navigate(`/courses/${c.id}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Couldn't create the course.");
      throw e;
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold sm:text-3xl">Courses</h1>
          <p className="mt-1 text-ink-muted">Each course is its own library of lectures, slides and books.</p>
        </div>
        <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>New course</Button>
      </header>

      {error && <ErrorState message={error.message} onRetry={reload} />}
      {loading && !courses && <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40" />)}</div>}

      {courses && courses.length === 0 && (
        <div className="card"><EmptyState icon={<BookOpen className="h-5 w-5" />} title="No courses yet"
          action={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>Create your first course</Button>}>
          Create a course, then upload lecture videos, textbooks and slides to it.
        </EmptyState></div>
      )}

      {courses && courses.length > 0 && (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {courses.map((c) => {
            const failed = c.status_counts.failed ?? 0;
            return (
              <li key={c.id}>
                <Link to={`/courses/${c.id}`} className="card group flex h-full flex-col p-5 transition-shadow hover:shadow-pop">
                  <div className="grid h-10 w-10 place-items-center rounded-xl bg-nova-50 text-nova-600"><FileText className="h-5 w-5" aria-hidden /></div>
                  <h2 className="mt-4 text-base font-semibold group-hover:text-nova-700">{c.title}</h2>
                  <p className="mt-1 line-clamp-2 text-sm text-ink-muted">{c.description || "No description"}</p>
                  <div className="mt-auto flex flex-wrap items-center gap-2 pt-5">
                    <Badge tone="neutral">{plural(c.document_count, "file")}</Badge>
                    {c.topic_count > 0 && <Badge tone="indigo">{plural(c.topic_count, "topic")}</Badge>}
                    {failed > 0 && <Badge tone="bad">{failed} need attention</Badge>}
                    <span className="ml-auto text-xs text-ink-muted">{timeAgo(c.updated_at)}</span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      <CourseDialog open={creating} mode="create" onClose={() => setCreating(false)} onSubmit={create} />
    </div>
  );
}
