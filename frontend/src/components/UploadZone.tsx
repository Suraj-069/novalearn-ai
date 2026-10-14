import { CheckCircle2, CircleAlert, Loader2, UploadCloud } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

import { useToast } from "@/hooks/useToast";
import { ApiError, api } from "@/services/api";

const ACCEPT = ".pdf,.pptx,.png,.jpg,.jpeg,.webp,.mp4,.m4v,.mov,.webm,.mkv,.vtt,.srt,.txt";

interface Item { name: string; state: "uploading" | "done" | "failed"; error?: string }

export function UploadZone({ courseId, onUploaded }: { courseId: string; onUploaded: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const toast = useToast();

  async function upload(files: File[]) {
    if (!files.length) return;
    setItems(files.map((f) => ({ name: f.name, state: "uploading" as const })));
    let ok = 0;
    for (const [i, f] of files.entries()) {
      try {
        await api.upload(courseId, f);
        ok++;
        onUploaded();
        setItems((l) => l.map((x, j) => (j === i ? { ...x, state: "done" as const } : x)));
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "Upload failed.";
        setItems((l) => l.map((x, j) => (j === i ? { ...x, state: "failed" as const, error: msg } : x)));
      }
    }
    setItems((l) => l.filter((x) => x.state === "failed")); // keep only failures on screen
    if (ok) toast.success(ok === 1 ? "File uploaded. Checking it now." : `${ok} files uploaded. Checking them now.`);
  }

  const onDrop = (e: DragEvent) => { e.preventDefault(); setDrag(false); void upload([...e.dataTransfer.files]); };
  const uploading = items.some((i) => i.state === "uploading");

  return (
    <div>
      <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
        className={`rounded-card border-2 border-dashed p-8 text-center transition-colors ${drag ? "border-nova-500 bg-nova-50" : "border-slate-300 bg-white"}`}>
        <div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-nova-50 text-nova-600">
          {uploading ? <Loader2 className="h-5 w-5 animate-spin" aria-hidden /> : <UploadCloud className="h-5 w-5" aria-hidden />}
        </div>
        <p className="mt-4 font-medium">Drop files here, or <button type="button" onClick={() => input.current?.click()} className="text-nova-600 underline-offset-2 hover:underline">browse</button></p>
        <p className="mt-1 text-sm text-ink-muted">PDF, PowerPoint (.pptx), images, lecture videos, and transcripts (.vtt, .srt, .txt)</p>
        <input ref={input} type="file" multiple accept={ACCEPT} className="sr-only" aria-label="Choose files to upload"
          onChange={(e) => { void upload([...(e.target.files ?? [])]); e.target.value = ""; }} />
      </div>
      {items.length > 0 && (
        <ul className="mt-3 space-y-2" aria-live="polite">
          {items.map((it, i) => (
            <li key={i} className={`flex items-start gap-3 rounded-ctl px-4 py-3 text-sm ${it.state === "failed" ? "bg-bad-soft text-bad" : "bg-slate-50 text-ink-soft"}`}>
              {it.state === "failed" ? <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> : it.state === "done" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden /> : <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" aria-hidden />}
              <div className="min-w-0"><div className="truncate font-medium">{it.name}</div>{it.error && <div>{it.error}</div>}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
