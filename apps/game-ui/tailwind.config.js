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
      },
      fontFamily: {
        sans: ["system-ui", "Avenir", "Helvetica", "Arial", "sans-serif"],
      },
    },
  },
  plugins: [],
};
