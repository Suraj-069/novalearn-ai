import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";

interface Props {
  open: boolean;
  mode: "create" | "rename";
  initial?: { title: string; description: string };
  onClose: () => void;
  onSubmit: (v: { title: string; description: string }) => Promise<void>;
}

export function CourseDialog({ open, mode, initial, onClose, onSubmit }: Props) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) { setTitle(initial?.title ?? ""); setDescription(initial?.description ?? ""); } }, [open, initial]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    try { await onSubmit({ title: title.trim(), description: description.trim() }); onClose(); }
    finally { setBusy(false); }
  }

  return (
    <Dialog open={open} onClose={onClose} title={mode === "create" ? "New course" : "Edit course"}
      description={mode === "create" ? "Give the subject a name. You can add material next." : undefined}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Course name" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={160} required />
        <div>
          <label htmlFor="cd" className="mb-1.5 block text-sm font-medium text-ink-soft">Description <span className="font-normal text-ink-muted">(optional)</span></label>
          <textarea id="cd" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} rows={3} className="input resize-none" />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={busy} disabled={!title.trim()}>{mode === "create" ? "Create course" : "Save changes"}</Button>
        </div>
      </form>
    </Dialog>
  );
}
