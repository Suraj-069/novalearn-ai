import { ExternalLink, FileText, FileVideo, Image as ImageIcon, MonitorPlay, RefreshCw, Repeat2, ScrollText, Trash2 } from "lucide-react";
import { useRef } from "react";

import { JobBadge } from "@/components/DocumentStatus";
import { Button } from "@/components/ui/Button";
import { formatBytes, formatDuration, plural, timeAgo } from "@/lib/format";
import type { DocumentItem } from "@/types";

const ICONS = { pdf: FileText, pptx: MonitorPlay, image: ImageIcon, video: FileVideo, transcript: ScrollText };
const LABELS = { pdf: "PDF", pptx: "Slides", image: "Image", video: "Video", transcript: "Transcript" };

/** One line of facts, built only from values the backend actually measured. */
export function describeDocument(d: DocumentItem): string[] {
  const parts: string[] = [];
  if (d.page_count != null) parts.push(plural(d.page_count, "page"));
  if (d.slide_count != null) parts.push(plural(d.slide_count, "slide"));
  if (d.duration_seconds != null) parts.push(formatDuration(d.duration_seconds));
  if (d.source_type === "image" && d.file_meta.width) parts.push(`${d.file_meta.width}×${d.file_meta.height}`);
  if (d.source_type === "pdf" && d.file_meta.likely_scanned) parts.push("scanned, needs OCR");
  if (d.source_type === "transcript") parts.push(d.file_meta.has_timestamps ? plural(Number(d.file_meta.timed_cues), "timed cue") : "no timestamps");
  const idx = d.file_meta.index as { chunks?: number } | undefined;
  if (idx?.chunks) parts.push(plural(idx.chunks, "passage"));
  parts.push(formatBytes(d.size_bytes));
  return parts;
}

interface Props {
  doc: DocumentItem;
  onOpen: () => void;
  onRetry: () => void;
  onReplace: (file: File) => void;
  onDelete: () => void;
}

export function DocumentRow({ doc, onOpen, onRetry, onReplace, onDelete }: Props) {
  const Icon = ICONS[doc.source_type];
  const replace = useRef<HTMLInputElement>(null);
  const index = doc.file_meta.index as { chunks?: number; warnings?: string[] } | undefined;
  const warnings = [
    ...(typeof doc.file_meta.warning === "string" ? [doc.file_meta.warning] : []),
    ...(index?.warnings ?? []),
  ];
  const busy = doc.job?.status === "processing" || doc.job?.status === "queued";

  return (
    <li className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 items-start gap-4">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-nova-50 text-nova-600"><Icon className="h-5 w-5" aria-hidden /></div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-medium">{doc.original_filename}</span>
            <JobBadge job={doc.job} />
          </div>
          <p className="mt-0.5 text-sm text-ink-muted">{LABELS[doc.source_type]} · {describeDocument(doc).join(" · ")} · {timeAgo(doc.created_at)}</p>
          {doc.job?.status === "failed" && doc.job.error && <p className="mt-1.5 text-sm text-bad">{doc.job.error}</p>}
          {warnings.map((w) => <p key={w} className="mt-1.5 text-sm text-warn">{w}</p>)}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5 pl-[60px] sm:pl-0">
        {doc.job?.status === "failed" && <Button size="sm" variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={onRetry}>Retry</Button>}
        <Button size="sm" variant="ghost" aria-label={`Open ${doc.original_filename}`} title="Open original" onClick={onOpen}><ExternalLink className="h-4 w-4" /></Button>
        <Button size="sm" variant="ghost" aria-label={`Replace ${doc.original_filename}`} title="Replace file" disabled={busy} onClick={() => replace.current?.click()}><Repeat2 className="h-4 w-4" /></Button>
        <Button size="sm" variant="ghost" aria-label={`Delete ${doc.original_filename}`} title="Delete" className="hover:!bg-bad-soft hover:text-bad" onClick={onDelete}><Trash2 className="h-4 w-4" /></Button>
        <input ref={replace} type="file" className="sr-only" aria-hidden tabIndex={-1} onChange={(e) => { const f = e.target.files?.[0]; if (f) onReplace(f); e.target.value = ""; }} />
      </div>
    </li>
  );
}
