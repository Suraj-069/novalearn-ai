import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
  icon?: ReactNode;
  size?: "sm" | "md";
}

const styles: Record<Variant, string> = {
  primary: "bg-nova-600 text-white hover:bg-nova-700 shadow-sm",
  secondary: "border border-line bg-white text-ink hover:bg-slate-50",
  ghost: "text-ink-soft hover:bg-slate-100",
  danger: "bg-bad text-white hover:bg-red-800",
};

export function Button({ variant = "primary", loading, icon, size = "md", className = "", children, disabled, ...rest }: Props) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-ctl font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55
        ${size === "sm" ? "px-3 py-1.5 text-[13px]" : "px-4 py-2.5 text-sm"} ${styles[variant]} ${className}`}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}
