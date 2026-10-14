import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, X } from "lucide-react";

type Tone = "success" | "error";
interface ToastItem { id: number; tone: Tone; message: string }

const Ctx = createContext<{ success: (m: string) => void; error: (m: string) => void } | null>(null);
let counter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const dismiss = (id: number) => setItems((l) => l.filter((t) => t.id !== id));
  const push = useCallback((tone: Tone, message: string) => {
    const id = ++counter;
    setItems((l) => [...l.slice(-3), { id, tone, message }]);
    setTimeout(() => setItems((l) => l.filter((t) => t.id !== id)), tone === "error" ? 7000 : 4000);
  }, []);

  return (
    <Ctx.Provider value={{ success: (m) => push("success", m), error: (m) => push("error", m) }}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 lg:bottom-6 lg:items-end lg:px-6" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} role={t.tone === "error" ? "alert" : "status"}
            className="pop-in pointer-events-auto flex max-w-md items-start gap-3 rounded-ctl border border-line bg-white px-4 py-3 text-sm shadow-pop">
            {t.tone === "success"
              ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden />
              : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-bad" aria-hidden />}
            <span className="text-ink-soft">{t.message}</span>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss" className="-mr-1 ml-1 rounded p-0.5 text-ink-muted hover:text-ink"><X className="h-4 w-4" /></button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useToast must be used inside <ToastProvider>");
  return v;
}
