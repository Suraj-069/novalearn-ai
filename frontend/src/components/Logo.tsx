import { useId } from "react";

/** Brand mark. Change BRAND here to rename the product everywhere in the UI. */
export const BRAND = { name: "NOVA Learn AI", short: "NOVA", tagline: "Learn smarter. Understand deeper." };

export function LogoMark({ className = "h-9 w-9" }: { className?: string }) {
  const gid = useId(); // unique per instance: a hidden SVG's gradient can't be referenced by another
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <defs><linearGradient id={gid} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#5b50e0" /><stop offset="1" stopColor="#7c3aed" /></linearGradient></defs>
      <rect width="32" height="32" rx="9" fill={`url(#${gid})`} />
      <path d="M9 23V9l14 14V9" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
