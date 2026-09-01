import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#070a0f", raised: "#0d121b", line: "#1b2230" },
        gain: "#00e08a",
        loss: "#ff5c5c",
        warn: "#ffc857",
        info: "#4da6ff",
        muted: "#6b7688",
        body: "#c7d0dd",
      },
      fontFamily: {
        // Mono stays the brand voice for anything numeric, tabular or
        // terminal-flavoured. Sans carries prose, which reads badly in mono at
        // headline sizes.
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
        sans: [
          "-apple-system", "BlinkMacSystemFont", "Inter", "Segoe UI",
          "Helvetica Neue", "Arial", "sans-serif",
        ],
      },
      maxWidth: { content: "1140px" },
    },
  },
  plugins: [],
};
export default config;
