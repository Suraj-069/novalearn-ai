import { Info } from "lucide-react";

import { useAsync } from "@/hooks/useAsync";
import { api } from "@/services/api";

/** Tells the user, plainly, what this installation can and can't do right now. */
export function CapabilityNote() {
  const { data } = useAsync(() => api.capabilities(), []);
  if (!data) return null;
  const notes: string[] = [];
  if (!data.llm.configured) notes.push("No language model is configured, so answers show the most relevant passages from your material rather than written explanations.");
  if (!data.embeddings.semantic) notes.push("Search matches words, not meaning (offline mode). Use terms from your notes for best results.");
  if (!notes.length) return null;
  return (
    <div className="flex items-start gap-3 rounded-ctl bg-nova-50 px-4 py-3 text-sm text-nova-800">
      <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="space-y-1">{notes.map((n) => <p key={n}>{n}</p>)}<p className="text-nova-700/80">Connect a model in <code>.env</code> to enable explanations (see README).</p></div>
    </div>
  );
}
