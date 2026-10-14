/** Brand tokens live here. Rename the product or recolour it by editing this file and src/styles/index.css. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#0f172a", soft: "#334155", muted: "#64748b" },
        canvas: "#f6f7fb",
        line: "#e3e6ef",
        nova: {
          950: "#17154a", 900: "#1e1b4b", 800: "#28257a", 700: "#3730a3",
          600: "#4338ca", 500: "#5b50e0", 100: "#e8e7fb", 50: "#f3f2fe",
        },
        violet: { DEFAULT: "#7c3aed", soft: "#f1e9fe" },
        cyan: { DEFAULT: "#0e8aa6", soft: "#e2f4f8" },
        ok: { DEFAULT: "#047857", soft: "#e3f5ee" },
        warn: { DEFAULT: "#b45309", soft: "#fdf1dc" },
        bad: { DEFAULT: "#b42318", soft: "#fde8e6" },
      },
      fontFamily: { sans: ['"Inter Variable"', "Inter", "system-ui", "sans-serif"] },
      borderRadius: { card: "16px", ctl: "12px" },
      boxShadow: {
        card: "0 1px 2px rgba(15,23,42,.04), 0 4px 16px -6px rgba(30,27,75,.10)",
        pop: "0 20px 50px -12px rgba(30,27,75,.35)",
      },
    },
  },
  plugins: [],
};
