import { ArrowLeft, BarChart3, Bot, ClipboardCheck, FlaskConical, FolderOpen, Network, Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { CourseDialog } from "@/components/CourseDialog";
import { DocumentRow } from "@/components/DocumentRow";
import { UploadZone } from "@/components/UploadZone";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { useAsync } from "@/hooks/useAsync";
import { plural } from "@/lib/format";
import { useToast } from "@/hooks/useToast";
import { ApiError, api } from "@/services/api";
import type { DocumentItem } from "@/types";

const inFlight = (docs: DocumentItem[]) => docs.some((d) => d.job?.status === "queued" || d.job?.status === "processing");

export default function CourseDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const course = useAsync(() => api.course(id), [id]);
  const docs = useAsync(() => api.documents(id), [id], { pollMs: 1500, pollWhile: inFlight });
  // Keep the course summary (topic count, indexed count) in step with background processing.
  const statusSig = docs.data?.map((d) => `${d.id}:${d.job?.status}`).join(",") ?? null;
  const lastSig = useRef<string | null>(null);
  useEffect(() => {
    if (statusSig !== null && lastSig.current !== null && statusSig !== lastSig.current) void course.reload();
    lastSig.current = statusSig;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusSig]);

  const [editing, setEditing] = useState(false);
  const [deleteCourse, setDeleteCourse] = useState(false);
  const [deleteDoc, setDeleteDoc] = useState<DocumentItem | null>(null);

  const fail = (fallback: string) => (e: unknown) => toast.error(e instanceof ApiError ? e.message : fallback);
  const refresh = () => { void docs.reload(); void course.reload(); };

  if (course.error) return <ErrorState message={course.error.message === "Course not found." ? "This course doesn't exist or you don't have access to it." : course.error.message} onRetry={course.reload} />;

  return (
    <div className="space-y-6">
      <Link to="/courses" className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink"><ArrowLeft className="h-4 w-4" aria-hidden />All courses</Link>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {course.data ? (<>
            <h1 className="break-words text-2xl font-semibold sm:text-3xl">{course.data.title}</h1>
            {course.data.description && <p className="mt-1 max-w-2xl text-ink-muted">{course.data.description}</p>}
          </>) : <Skeleton className="h-9 w-72" />}
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" icon={<Pencil className="h-4 w-4" />} onClick={() => setEditing(true)} disabled={!course.data}>Edit</Button>
          <Button variant="secondary" icon={<Trash2 className="h-4 w-4" />} onClick={() => setDeleteCourse(true)} disabled={!course.data} className="text-bad">Delete</Button>
        </div>
      </header>

      <UploadZone courseId={id} onUploaded={refresh} />

      {(course.data?.status_counts.indexed ?? 0) > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-card bg-gradient-to-r from-nova-700 to-violet p-5 text-white">
          <div><p className="font-semibold">{plural(course.data!.topic_count, "topic")} found in {plural(course.data!.status_counts.indexed, "indexed file")}</p>
            <p className="text-sm text-white/80">Ask questions with citations, or explore how the material is organised.</p></div>
          <div className="flex flex-wrap gap-2">
            <Link to={`/courses/${id}/tutor`} className="inline-flex items-center gap-2 rounded-ctl bg-white px-4 py-2.5 text-sm font-semibold text-nova-700 hover:bg-nova-50"><Bot className="h-4 w-4" aria-hidden />Ask the tutor</Link>
            <Link to={`/courses/${id}/knowledge`} className="inline-flex items-center gap-2 rounded-ctl bg-white/15 px-4 py-2.5 text-sm font-semibold hover:bg-white/25"><Network className="h-4 w-4" aria-hidden />Knowledge explorer</Link>
            <Link to={`/courses/${id}/assessments`} className="inline-flex items-center gap-2 rounded-ctl bg-white/15 px-4 py-2.5 text-sm font-semibold hover:bg-white/25"><ClipboardCheck className="h-4 w-4" aria-hidden />Practice</Link>
            <Link to={`/courses/${id}/analytics`} className="inline-flex items-center gap-2 rounded-ctl bg-white/15 px-4 py-2.5 text-sm font-semibold hover:bg-white/25"><BarChart3 className="h-4 w-4" aria-hidden />Analytics</Link>
            <Link to={`/courses/${id}/evaluation`} className="inline-flex items-center gap-2 rounded-ctl bg-white/15 px-4 py-2.5 text-sm font-semibold hover:bg-white/25"><FlaskConical className="h-4 w-4" aria-hidden />Evaluation</Link>
          </div>
        </div>
      )}

      <section className="card overflow-hidden" aria-labelledby="mat-h">
        <h2 id="mat-h" className="border-b border-line px-5 py-4 text-base font-semibold">Course material {docs.data && <span className="font-normal text-ink-muted">({docs.data.length})</span>}</h2>
        {docs.error && <div className="p-4"><ErrorState message={docs.error.message} onRetry={docs.reload} /></div>}
        {docs.loading && !docs.data && <div className="space-y-3 p-5"><Skeleton className="h-14" /><Skeleton className="h-14" /></div>}
        {docs.data && docs.data.length === 0 && <EmptyState icon={<FolderOpen className="h-5 w-5" />} title="No material yet">Upload your first lecture, slide deck or textbook above.</EmptyState>}
        {docs.data && docs.data.length > 0 && (
          <ul className="divide-y divide-line">
            {docs.data.map((d) => (
              <DocumentRow key={d.id} doc={d}
                onOpen={() => api.openDocument(d.id).catch(fail("Couldn't open this file."))}
                onRetry={() => api.retryDocument(d.id).then(() => { toast.success("Checking the file again."); refresh(); }).catch(fail("Couldn't retry."))}
                onReplace={(f) => api.replaceDocument(d.id, f).then(() => { toast.success("File replaced."); refresh(); }).catch(fail("Couldn't replace the file."))}
                onDelete={() => setDeleteDoc(d)} />
            ))}
          </ul>
        )}
      </section>

      <CourseDialog open={editing} mode="rename" initial={course.data ? { title: course.data.title, description: course.data.description } : undefined}
        onClose={() => setEditing(false)}
        onSubmit={(v) => api.updateCourse(id, v).then((c) => { course.setData(c); toast.success("Course updated."); }).catch((e) => { fail("Couldn't save changes.")(e); throw e; })} />

      <Dialog open={deleteCourse} onClose={() => setDeleteCourse(false)} title="Delete this course?" description="This permanently removes the course and every file in it. This can't be undone.">
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setDeleteCourse(false)}>Cancel</Button>
          <Button variant="danger" onClick={() => api.deleteCourse(id).then(() => { toast.success("Course deleted."); navigate("/courses"); }).catch(fail("Couldn't delete the course."))}>Delete course</Button>
        </div>
      </Dialog>

      <Dialog open={deleteDoc !== null} onClose={() => setDeleteDoc(null)} title="Delete this file?" description={deleteDoc ? `“${deleteDoc.original_filename}” will be removed from this course.` : undefined}>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setDeleteDoc(null)}>Cancel</Button>
          <Button variant="danger" onClick={() => { const d = deleteDoc!; setDeleteDoc(null); api.deleteDocument(d.id).then(() => { toast.success("File deleted."); refresh(); }).catch(fail("Couldn't delete the file.")); }}>Delete file</Button>
        </div>
      </Dialog>
    </div>
  );
}
