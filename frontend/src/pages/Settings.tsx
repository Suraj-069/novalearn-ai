import { Download, LogOut, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { useAuth } from "@/hooks/useAuth";
import { useToast } from "@/hooks/useToast";
import { ApiError, api } from "@/services/api";
import type { User } from "@/types";

const STYLES: { id: User["explanation_style"]; label: string }[] = [
  { id: "simple", label: "Short and simple" }, { id: "balanced", label: "Balanced" },
  { id: "detailed", label: "Thorough" }, { id: "examples", label: "Example-first" },
];
const LANGUAGES = ["English", "Hindi", "Marathi", "Spanish", "French", "German"];

function Section({ title, text, children }: { title: string; text?: string; children: React.ReactNode }) {
  return (
    <section className="card p-6">
      <h2 className="text-base font-semibold">{title}</h2>
      {text && <p className="mt-1 text-sm text-ink-muted">{text}</p>}
      <div className="mt-5">{children}</div>
    </section>
  );
}

export default function SettingsPage() {
  const { user, setUser, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [name, setName] = useState(user?.name ?? "");
  const [goals, setGoals] = useState((user?.learning_goals ?? []).join("\n"));
  const [style, setStyle] = useState(user?.explanation_style ?? "balanced");
  const [language, setLanguage] = useState(user?.language ?? "English");
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [typed, setTyped] = useState("");

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const updated = await api.updateProfile({
        name: name.trim() || user?.name, explanation_style: style, language,
        learning_goals: goals.split("\n").map((g) => g.trim()).filter(Boolean),
      });
      setUser(updated);
      toast.success("Settings saved.");
    } catch (err) { toast.error(err instanceof ApiError ? err.message : "Couldn't save settings."); }
    finally { setSaving(false); }
  }

  async function exportData() {
    try {
      const data = await api.exportData();
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: "nova-learn-export.json" });
      a.click(); URL.revokeObjectURL(url);
      toast.success("Export downloaded.");
    } catch (err) { toast.error(err instanceof ApiError ? err.message : "Couldn't export your data."); }
  }

  async function deleteAccount() {
    try { await api.deleteAccount(); logout(); navigate("/signup"); toast.success("Your account and files were deleted."); }
    catch (err) { toast.error(err instanceof ApiError ? err.message : "Couldn't delete your account."); }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <header><h1 className="text-2xl font-semibold sm:text-3xl">Settings</h1><p className="mt-1 text-ink-muted">Your profile and how the tutor should talk to you.</p></header>

      <form onSubmit={save} className="space-y-6">
        <Section title="Profile">
          <div className="space-y-4">
            <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
            <Field label="Email" value={user?.email ?? ""} disabled hint="Email can't be changed in this version." />
          </div>
        </Section>

        <Section title="Learning goals" text="One goal per line. These guide the practice and revision we suggest.">
          <label htmlFor="goals" className="sr-only">Learning goals</label>
          <textarea id="goals" value={goals} onChange={(e) => setGoals(e.target.value)} rows={4} className="input resize-none" placeholder="Pass the final exam&#10;Understand entropy properly" />
        </Section>

        <Section title="Explanations">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="style" className="mb-1.5 block text-sm font-medium text-ink-soft">Preferred style</label>
              <select id="style" value={style} onChange={(e) => setStyle(e.target.value as User["explanation_style"])} className="input">
                {STYLES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="language" className="mb-1.5 block text-sm font-medium text-ink-soft">Language</label>
              <select id="language" value={language} onChange={(e) => setLanguage(e.target.value)} className="input">
                {LANGUAGES.map((l) => <option key={l}>{l}</option>)}
              </select>
            </div>
          </div>
        </Section>
        <div className="flex justify-end"><Button type="submit" loading={saving}>Save changes</Button></div>
      </form>

      <Section title="Your data" text="Download what we store about you, or delete everything.">
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" icon={<Download className="h-4 w-4" />} onClick={exportData}>Export my data</Button>
          <Button variant="secondary" className="text-bad" icon={<Trash2 className="h-4 w-4" />} onClick={() => setConfirmDelete(true)}>Delete my account</Button>
        </div>
      </Section>

      <Section title="Session">
        <Button variant="secondary" icon={<LogOut className="h-4 w-4" />} onClick={() => { logout(); navigate("/login"); }}>Sign out</Button>
      </Section>

      <Dialog open={confirmDelete} onClose={() => { setConfirmDelete(false); setTyped(""); }} title="Delete your account?"
        description="This permanently deletes your profile, courses, uploaded files and history. It can't be undone.">
        <Field label={`Type ${user?.email} to confirm`} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => { setConfirmDelete(false); setTyped(""); }}>Cancel</Button>
          <Button variant="danger" disabled={typed !== user?.email} onClick={deleteAccount}>Delete everything</Button>
        </div>
      </Dialog>
    </div>
  );
}
