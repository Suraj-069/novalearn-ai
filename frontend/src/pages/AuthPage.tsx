import { BookMarked, Eye, EyeOff, FileSearch, TrendingUp } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { BRAND, LogoMark } from "@/components/Logo";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { useAuth } from "@/hooks/useAuth";
import { ApiError } from "@/services/api";

const POINTS = [
  { icon: FileSearch, title: "Answers that point to the page", text: "Every explanation links back to the slide, page or video moment it came from." },
  { icon: BookMarked, title: "One place for scattered material", text: "Lectures, textbooks and slides become a single course you can question." },
  { icon: TrendingUp, title: "Practice that adapts", text: "Quizzes follow what you actually got wrong, not what you hoped to skip." },
];

export default function AuthPage({ mode }: { mode: "login" | "signup" }) {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const signup = mode === "signup";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const user = signup ? await register(name, email, password) : await login(email, password);
      navigate(user.onboarded ? from : "/onboarding", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    } finally { setBusy(false); }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <section className="relative hidden overflow-hidden bg-gradient-to-br from-nova-900 via-nova-800 to-violet p-12 text-white lg:flex lg:flex-col">
        <div className="flex items-center gap-3"><LogoMark /><span className="text-lg font-semibold">{BRAND.name}</span></div>
        <div className="my-auto max-w-lg">
          <h1 className="text-4xl font-semibold leading-tight">{BRAND.tagline}</h1>
          <p className="mt-4 text-lg text-white/75">A study companion that only tells you what your own course material supports.</p>
          <ul className="mt-10 space-y-6">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white/15"><Icon className="h-5 w-5" aria-hidden /></div>
                <div><div className="font-medium">{title}</div><div className="text-sm text-white/70">{text}</div></div>
              </li>
            ))}
          </ul>
        </div>
        <div aria-hidden className="pointer-events-none absolute -bottom-32 -right-24 h-80 w-80 rounded-full bg-cyan/30 blur-3xl" />
      </section>

      <section className="flex items-center justify-center px-5 py-10 sm:px-10">
        <form onSubmit={submit} className="w-full max-w-sm" noValidate>
          <div className="mb-8 flex items-center gap-3 lg:hidden"><LogoMark /><span className="text-lg font-semibold">{BRAND.name}</span></div>
          <h2 className="text-2xl font-semibold">{signup ? "Create your account" : "Welcome back"}</h2>
          <p className="mt-1.5 text-sm text-ink-muted">{signup ? "Start building a study space from your own material." : "Sign in to pick up where you left off."}</p>

          <div className="mt-8 space-y-4">
            {signup && <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />}
            <Field label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
            <Field label="Password" type={show ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete={signup ? "new-password" : "current-password"} required minLength={signup ? 8 : undefined}
              hint={signup ? "At least 8 characters." : undefined}
              trailing={<button type="button" onClick={() => setShow(!show)} aria-label={show ? "Hide password" : "Show password"} className="rounded-lg p-1.5 text-ink-muted hover:text-ink">
                {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button>} />
          </div>

          {error && <p role="alert" className="mt-4 rounded-ctl bg-bad-soft px-3.5 py-2.5 text-sm text-bad">{error}</p>}
          <Button type="submit" loading={busy} className="mt-6 w-full">{signup ? "Create account" : "Sign in"}</Button>

          <p className="mt-6 text-center text-sm text-ink-muted">
            {signup ? "Already have an account? " : "New here? "}
            <Link to={signup ? "/login" : "/signup"} className="font-medium text-nova-600 hover:underline">{signup ? "Sign in" : "Create an account"}</Link>
          </p>
        </form>
      </section>
    </div>
  );
}
