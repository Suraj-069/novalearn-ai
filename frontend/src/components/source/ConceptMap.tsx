import type { Topic } from "@/types";

interface Props { topics: Topic[]; selectedId: string | null; onSelect: (id: string) => void }

/** Circular concept map: node size = amount of material, arrows point from prerequisite to dependent topic. */
export function ConceptMap({ topics, selectedId, onSelect }: Props) {
  const top = topics.filter((t) => !t.parent_id);
  const W = 720, H = 360, cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 70;
  const max = Math.max(1, ...top.map((t) => t.chunk_count));
  const pos = new Map(top.map((t, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, top.length) - Math.PI / 2;
    return [t.id, { x: top.length === 1 ? cx : cx + R * Math.cos(a), y: top.length === 1 ? cy : cy + R * Math.sin(a), r: 16 + 20 * Math.sqrt(t.chunk_count / max) }] as const;
  }));
  const edges = top.flatMap((t) => t.prerequisites.map((p) => ({ from: p.id, to: t.id }))).filter((e) => pos.has(e.from) && pos.has(e.to));

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto h-auto w-full min-w-[480px] max-w-4xl" role="group" aria-label="Concept map of course topics">
        <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#7c3aed" /></marker></defs>
        {edges.map((e, i) => {
          const a = pos.get(e.from)!, b = pos.get(e.to)!;
          const d = Math.hypot(b.x - a.x, b.y - a.y) || 1;
          return <line key={i} x1={a.x + ((b.x - a.x) / d) * a.r} y1={a.y + ((b.y - a.y) / d) * a.r} x2={b.x - ((b.x - a.x) / d) * (b.r + 4)} y2={b.y - ((b.y - a.y) / d) * (b.r + 4)} stroke="#7c3aed" strokeWidth="1.8" markerEnd="url(#arrow)" opacity="0.8" />;
        })}
        {top.map((t) => {
          const p = pos.get(t.id)!;
          const on = t.id === selectedId;
          return (
            <g key={t.id} role="button" tabIndex={0} aria-label={`${t.name}, ${t.chunk_count} passages`} aria-pressed={on} className="cursor-pointer outline-none"
              onClick={() => onSelect(t.id)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(t.id))}>
              <circle cx={p.x} cy={p.y} r={p.r} fill={on ? "#4338ca" : "#e8e7fb"} stroke={on ? "#1e1b4b" : "#5b50e0"} strokeWidth={on ? 3 : 1.5} />
              <text x={p.x} y={p.y + p.r + 16} textAnchor="middle" fontSize="13" fontWeight={on ? 700 : 500} fill="#0f172a">{t.name.length > 24 ? t.name.slice(0, 23) + "…" : t.name}</text>
            </g>
          );
        })}
      </svg>
      <p className="mt-1 text-center text-xs text-ink-muted">Bigger circle = more material. Arrows point from a prerequisite to the topic that builds on it.</p>
    </div>
  );
}
