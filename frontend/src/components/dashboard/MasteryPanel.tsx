import { BarChart3 } from "lucide-react";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState } from "@/components/ui/Feedback";
import type { TopicMastery } from "@/types";

const color = (m: number) => (m < 0.5 ? "#b45309" : m < 0.75 ? "#5b50e0" : "#047857");

export function MasteryPanel({ mastery }: { mastery: TopicMastery[] }) {
  return (
    <section className="card p-6" aria-labelledby="mastery-h">
      <h2 id="mastery-h" className="text-base font-semibold">Topic mastery</h2>
      <p className="mt-1 text-sm text-ink-muted">Estimates from your quiz answers. They are not a guaranteed measure of what you know.</p>
      {mastery.length === 0 ? (
        <EmptyState icon={<BarChart3 className="h-5 w-5" />} title="No mastery data yet">
          Your estimates appear here after your first quiz. Until then, nothing is assumed about what you know.
        </EmptyState>
      ) : (
        <div className="mt-4 h-72">
          <ResponsiveContainer width="100%" height={Math.max(160, mastery.length * 36)}>
            <BarChart data={mastery.map((m) => ({ name: m.topic_name, pct: Math.round(m.mastery * 100) }))} layout="vertical" margin={{ left: 8, right: 16 }}>
              <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 12, fill: "#64748b" }} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 12, fill: "#334155" }} axisLine={false} tickLine={false} />
              <Tooltip formatter={(v: number) => [`${v}% (estimate)`, "Mastery"]} cursor={{ fill: "#f3f2fe" }} />
              <Bar dataKey="pct" radius={[0, 8, 8, 0]} barSize={16}>
                {mastery.map((m) => <Cell key={m.topic_id} fill={color(m.mastery)} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
