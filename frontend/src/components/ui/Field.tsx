import { useId, type InputHTMLAttributes, type ReactNode } from "react";

interface Props extends InputHTMLAttributes<HTMLInputElement> { label: string; hint?: string; error?: string | null; trailing?: ReactNode }

export function Field({ label, hint, error, className = "", trailing, ...rest }: Props) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink-soft">{label}</label>
      <div className="relative">
        <input id={id} {...rest} aria-invalid={Boolean(error)} aria-describedby={hint || error ? `${id}-d` : undefined} className="input" />
        {trailing && <div className="absolute inset-y-0 right-2 flex items-center">{trailing}</div>}
      </div>
      {(error || hint) && <p id={`${id}-d`} className={`mt-1.5 text-[13px] ${error ? "text-bad" : "text-ink-muted"}`}>{error ?? hint}</p>}
    </div>
  );
}
