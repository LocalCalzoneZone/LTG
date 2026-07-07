/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // MTG-ish mana colours for pips / identity icons.
        mana: {
          W: "#f8f4d8",
          U: "#3b7fd4",
          B: "#5a4a63",
          R: "#d64f42",
          G: "#4a9b5f",
          C: "#b3b3b3",
        },
        // "Brasswork & Ink" design tokens (see design mockup).
        ink: {
          0: "#07090c", // page
          1: "#0b0e14", // battlefield
          2: "#10131b", // panel
          3: "#161a24", // raised surface
        },
        brass: {
          DEFAULT: "#c9b37e",
          hi: "#ecdcae",
        },
        parch: "#e8e4d8", // warm parchment-white text
        mist: "#98a0ae", // secondary text
        dimmed: "#59616e", // tertiary text
        tide: "#82b4c9", // player allegiance
        blood: {
          DEFAULT: "#c25a50", // enemy allegiance / damage
          deep: "#571f1e",
        },
        vigor: "#84c793", // heal / buff
        spell: "#8fb8d8", // spell lane
        aether: "#b39ddb", // ability lane / channelling
        // brass hairlines
        line: "rgba(214,197,160,0.13)",
        line2: "rgba(214,197,160,0.30)",
      },
      fontFamily: {
        sans: ["-apple-system", "SF Pro Text", "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif"],
        display: ["Optima", "Candara", "Gill Sans", "Segoe UI", "ui-sans-serif", "sans-serif"],
      },
    },
  },
  plugins: [],
};
