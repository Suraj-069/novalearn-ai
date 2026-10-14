import { Info } from "lucide-react";

export function MasteryNote({ text }: { text?: string }) {
  return (
    <p className="flex items-start gap-2 text-[13px] text-ink-muted">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      {text ?? "Mastery is an estimate computed from your answers with a simple statistical model. It is not a measurement of what you actually know."}
    </p>
  );
}
