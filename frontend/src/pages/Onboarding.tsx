import { ArrowLeft, Check } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { BRAND, LogoMark } from "@/components/Logo";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { useAuth } from "@/hooks/useAuth";
import { useToast } from "@/hooks/useToast";
import { ApiError, api } from "@/services/api";
import type { User } from "@/types";

const GOALS = ["Pass an upcoming exam", "Understand the basics", "Go deeper on hard topics", "Keep up during the term", "Revise before a test", "Prepare for interviews"];
const STYLES: { id: User["explanation_style"]; title: string; text: string }[] = [
  { id: "simple", title: "Short and simple", text: "Plain language, the key point first." },
  { id: "balanced", title: "Balanced", text: "A clear explanation with one example." },
  { id: "detailed", title: "Thorough", text: "Full reasoning, step by step." },
  { id: "examples", title: "Example-first", text: "Start from a worked example." },
];
const LANGUAGES = ["English", "Hindi", "Marathi", "Spanish", "French", "German"];

export default function Onboarding() {
  const { user, setUser } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [goals, setGoals] = useState<string[]>(user?.learning_goals ?? []);
  const [style, setStyle] = useState<User["explanation_style"]>(user?.explanation_style ?? "balanced");
  const [language, setLanguage] = useState(user?.language ?? "English");
  const [course, setCourse] = useState("");
  const [busy, setBusy] = useState(false);

  const toggle = (g: string) => setGoals((l) => (l.includes(g) ? l.filter((x) => x !== g) : [...l, g]));

  async function finish() {
    setBusy(true);
    try {
      const updated = await api.updateProfile({ learning_goals: goals, explanation_style: style, language, onboarded: true });
      setUser(updated);
      if (course.trim()) {
        const c = await api.createCourse({ title: course.trim() });
        navigate(`/courses/${c.id}`, { replace: true });
      } else navigate("/", { replace: true });
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Couldn't save your preferences.");
    } finally { setBusy(false); }
  }

  const steps = [
    { title: "What are you working toward?", sub: "Pick any that fit. This shapes the practice we suggest." },
    { title: "How do you like things explained?", sub: "You can change this any time in Settings." },
    { title: "Add your first course", sub: "A course is a folder for the lectures, slides and books of one subject." },
  ];

  return (
    <div className="mx-auto flex min-h-screen max-w-xl flex-col px-5 py-8 sm:py-14">
      <div className="flex items-center gap-3"><LogoMark className="h-8 w-8" /><span className="font-semibold">{BRAND.name}</span></div>
      <div className="mt-10 flex gap-2" role="progressbar" aria-valuenow={step + 1} aria-valuemin={1} aria-valuemax={3} aria-label="Setup progress">
        {steps.map((_, i) => <div key={i} className={`h-1.5 flex-1 rounded-full ${i <= step ? "bg-nova-600" : "bg-slate-200"}`} />)}
      </div>
      <h1 className="mt-8 text-2xl font-semibold">{steps[step].title}</h1>
      <p className="mt-1.5 text-ink-muted">{steps[step].sub}</p>

      <div className="mt-8 flex-1">
        {step === 0 && (
          <div className="flex flex-wrap gap-2.5">
            {GOALS.map((g) => (
              <button key={g} type="button" onClick={() => toggle(g)} aria-pressed={goals.includes(g)}
                className={`flex items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-medium transition-colors ${goals.includes(g) ? "border-nova-600 bg-nova-50 text-nova-700" : "border-line bg-white text-ink-soft hover:border-slate-300"}`}>
                {goals.includes(g) && <Check className="h-4 w-4" aria-hidden />}{g}
              </button>
            ))}
          </div>
        )}
        {step === 1 && (
          <div className="space-y-6">
            <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Explanation style">
              {STYLES.map((s) => (
                <button key={s.id} type="button" role="radio" aria-checked={style === s.id} onClick={() => setStyle(s.id)}
                  className={`rounded-card border p-4 text-left transition-colors ${style === s.id ? "border-nova-600 bg-nova-50" : "border-line bg-white hover:border-slate-300"}`}>
                  <div className="font-medium">{s.title}</div><div className="mt-1 text-sm text-ink-muted">{s.text}</div>
                </button>
              ))}
            </div>
            <div>
              <label htmlFor="lang" className="mb-1.5 block text-sm font-medium text-ink-soft">Preferred language for explanations</label>
              <select id="lang" value={language} onChange={(e) => setLanguage(e.target.value)} className="input">
                {LANGUAGES.map((l) => <option key={l}>{l}</option>)}
              </select>
            </div>
          </div>
        )}
        {step === 2 && (
          <div className="space-y-4">
            <Field label="Course name" placeholder="e.g. Thermodynamics, Semester 3" value={course} onChange={(e) => setCourse(e.target.value)} maxLength={160} autoFocus />
            <p className="rounded-ctl bg-nova-50 p-4 text-sm text-nova-800">
              After you upload material, a short diagnostic quiz will establish your starting point, so recommendations don't assume you already know the subject.
            </p>
          </div>
        )}
      </div>

      <div className="mt-10 flex items-center justify-between">
        {step > 0 ? <Button variant="ghost" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => setStep(step - 1)}>Back</Button> : <span />}
        {step < 2
          ? <Button onClick={() => setStep(step + 1)}>Continue</Button>
          : <Button loading={busy} onClick={finish}>{course.trim() ? "Create course and finish" : "Skip and finish"}</Button>}
      </div>
    </div>
  );
}
