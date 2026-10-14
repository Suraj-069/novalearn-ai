export const pct = (v: number) => `${Math.round(v * 100)}%`;
/** Estimates built on very few answers swing a lot, so the UI says so. */
export const EARLY_BELOW = 3;
export const isEarly = (evidence: number) => evidence < EARLY_BELOW;
export const masteryTone = (m: number | null): "neutral" | "warn" | "indigo" | "ok" => (m == null ? "neutral" : m < 0.4 ? "warn" : m < 0.75 ? "indigo" : "ok");
export const MODE_LABEL: Record<string, string> = { quiz: "Quiz", mock_exam: "Mock exam", diagnostic: "Diagnostic" };
