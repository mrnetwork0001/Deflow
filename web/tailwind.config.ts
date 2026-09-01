import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Near-black canvas with two raised surfaces, so cards separate from
        // the page without a heavy border.
        ink: {
          DEFAULT: "#08090b",
          raised: "#0e1013",
          card: "#121519",
          line: "#1e2229",
          hair: "#262b33",
        },
        gain: { DEFAULT: "#00e08a", dim: "#00b06c" },
        loss: "#ff5a5a",
        warn: "#ffc857",
        info: "#4da6ff",
        body: "#dfe4ea",
        muted: "#7c8595",
        faint: "#525b6b",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
        sans: [
          "-apple-system", "BlinkMacSystemFont", "Inter", "Segoe UI",
          "Helvetica Neue", "Arial", "sans-serif",
        ],
      },
      // Gutters reduced 30%: at 1920px a 1200px cap left ~360px either side,
      // 1416px leaves ~252px.
      maxWidth: { content: "1416px", prose: "710px" },
      letterSpacing: { tightest: "-0.035em" },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(14px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        drift: {
          "0%,100%": { transform: "translateX(0)" },
          "50%": { transform: "translateX(-24px)" },
        },
      },
      animation: {
        rise: "rise .7s cubic-bezier(.2,.7,.3,1) both",
        drift: "drift 26s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
export default config;
