import type { ReactNode } from "react";

export type Tone = "neutral" | "indigo" | "cyan" | "ok" | "warn" | "bad";
const tones: Record<Tone, string> = {
  neutral: "bg-slate-100 text-ink-soft",
  indigo: "bg-nova-50 text-nova-700",
  cyan: "bg-cyan-soft text-cyan",
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
};

export function Badge({ tone = "neutral", icon, children }: { tone?: Tone; icon?: ReactNode; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${tones[tone]}`}>
      {icon}{children}
    </span>
  );
}
