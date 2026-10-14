import { ExternalLink, FileText, Loader2, Sparkles, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { formatTimestamp } from "@/lib/format";
import { figureImageUrl, mediaToken, mediaUrl, pageImageUrl } from "@/lib/media";
import { api } from "@/services/api";
import type { Citation, SlideView } from "@/types";

/** Human-readable location, built only from fields the citation really has. */
export function locationLabel(c: Citation): string {
  if (c.page) return `page ${c.page}`;
  if (c.slide) return `slide ${c.slide}`;
  if (c.start_seconds != null) return `${formatTimestamp(c.start_seconds)}${c.end_seconds != null ? `–${formatTimestamp(c.end_seconds)}` : ""}`;
  if (c.figure_ref) return "figure";
  return "text";
}

function PdfPage({ c }: { c: Citation }) {
  const [url, setUrl] = useState<{ img: string; file: string } | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let live = true;
    setUrl(null); setErr(false);
    mediaToken(c.document_id).then((t) => live && setUrl({ img: pageImageUrl(c.document_id, c.page!, t), file: `${mediaUrl(c.document_id, t)}#page=${c.page}` })).catch(() => live && setErr(true));
    return () => { live = false; };
  }, [c.document_id, c.page]);
  if (err) return <p className="text-sm text-bad">Couldn't load this page.</p>;
  if (!url) return <div className="skeleton h-64" />;
  return (
    <div>
      <img src={url.img} alt={`${c.filename}, page ${c.page}`} className="w-full rounded-ctl border border-line" onError={() => setErr(true)} />
      <a href={url.file} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-nova-600 hover:underline">
        <ExternalLink className="h-3.5 w-3.5" aria-hidden />Open the PDF at page {c.page}
      </a>
    </div>
  );
}

function SlidePreview({ c }: { c: Citation }) {
  const [slide, setSlide] = useState<SlideView | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    setSlide(null); setErr(false);
    api.slide(c.document_id, c.slide!).then(setSlide).catch(() => setErr(true));
  }, [c.document_id, c.slide]);
  if (err) return <p className="text-sm text-bad">Couldn't load this slide.</p>;
  if (!slide) return <div className="skeleton h-40" />;
  return (
    <div className="rounded-ctl border border-line bg-white p-4">
      <p className="text-xs text-ink-muted">Slide {slide.slide} of {slide.of} · text content of the slide</p>
      {slide.title && <h4 className="mt-2 text-base font-semibold">{slide.title}</h4>}
      <ul className="mt-2 space-y-1.5 text-sm text-ink-soft">{slide.text.map((t, i) => <li key={i} className="whitespace-pre-wrap">{t}</li>)}</ul>
      {slide.notes && <p className="mt-3 border-t border-line pt-3 text-sm text-ink-muted"><span className="font-medium">Speaker notes:</span> {slide.notes}</p>}
    </div>
  );
}

function VideoAt({ c }: { c: Citation }) {
  const [src, setSrc] = useState<string | null>(null);
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => { mediaToken(c.document_id).then((t) => setSrc(mediaUrl(c.document_id, t))).catch(() => setSrc("")); }, [c.document_id]);
  if (src === null) return <div className="skeleton h-48" />;
  if (!src) return <p className="text-sm text-bad">Couldn't load the video.</p>;
  const seek = () => { if (ref.current && c.start_seconds != null) ref.current.currentTime = c.start_seconds; };
  return (
    <div>
      <video ref={ref} src={src} controls preload="metadata" onLoadedMetadata={seek} className="w-full rounded-ctl bg-black" />
      <button type="button" onClick={() => { seek(); void ref.current?.play(); }} className="mt-2 text-sm font-medium text-nova-600 hover:underline">
        Jump to {formatTimestamp(c.start_seconds ?? 0)}
      </button>
    </div>
  );
}

function ImageFigure({ c }: { c: Citation }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => { mediaToken(c.document_id).then((t) => setSrc(mediaUrl(c.document_id, t))).catch(() => setSrc("")); }, [c.document_id]);
  return src ? <img src={src} alt={c.figure_ref ?? "figure"} className="max-h-72 rounded-ctl border border-line" /> : <div className="skeleton h-40" />;
}

export function FigurePreview({ citation: c, compact = false }: { citation: Citation; compact?: boolean }) {
  const [src, setSrc] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let live = true;
    setSrc(null); setErr(false);
    if (!c.figure_ref) return () => { live = false; };
    mediaToken(c.document_id)
      .then((t) => live && setSrc(figureImageUrl(c.document_id, c.figure_ref!, t)))
      .catch(() => live && setErr(true));
    return () => { live = false; };
  }, [c.document_id, c.figure_ref]);
  if (err) return compact ? null : <p className="text-sm text-bad">Couldn't load this figure from the source.</p>;
  if (!src) return <div className={`skeleton ${compact ? "h-24 w-36" : "h-40 w-full"}`} />;
  return <img src={src} alt={`Figure ${c.figure_ref} from ${c.filename ?? "course source"}`} className={`rounded-ctl border border-line object-contain ${compact ? "max-h-28 max-w-40" : "max-h-96 w-full"}`} onError={() => setErr(true)} />;
}

/** Opens a citation at its exact location: PDF page, slide, or video/transcript timestamp. */
export function SourceViewer({ citation: c, full }: { citation: Citation; full?: string }) {
  if (!c.available) {
    return (
      <div className="flex items-start gap-3 rounded-ctl bg-warn-soft p-4 text-sm text-warn">
        <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <p>This source was removed from the course after the answer was given, so it can't be shown.</p>
      </div>
    );
  }
  const isVideoTime = c.start_seconds != null && c.source_type === "video";
  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <FileText className="h-4 w-4 text-nova-600" aria-hidden />
          <span className="font-medium">{c.filename}</span>
          <Badge tone="indigo">{locationLabel(c)}</Badge>
          {c.ai_generated && <Badge tone="warn" icon={<Sparkles className="h-3 w-3" />}>AI-written description</Badge>}
        </div>
      </div>
      <blockquote className="rounded-ctl border-l-4 border-nova-500 bg-nova-50 px-4 py-3 text-sm text-ink-soft">{full ?? c.text ?? c.excerpt}</blockquote>
      {c.source_type === "pdf" && c.page && <PdfPage c={c} />}
      {c.source_type === "pptx" && c.slide && <SlidePreview c={c} />}
      {(c.source_type === "pdf" || c.source_type === "pptx") && c.figure_ref && <FigurePreview citation={c} />}
      {isVideoTime && <VideoAt c={c} />}
      {c.source_type === "transcript" && c.start_seconds != null && (
        <p className="text-sm text-ink-muted">Transcript time {formatTimestamp(c.start_seconds)}. Upload the lecture video to this course to watch it from here.</p>
      )}
      {c.source_type === "image" && <ImageFigure c={c} />}
    </div>
  );
}

export function Spinner() { return <Loader2 className="h-4 w-4 animate-spin" aria-hidden />; }
