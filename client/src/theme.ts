import { createTheme } from "@mui/material/styles";

// Mirrors the CSS custom properties in index.css (--accent, --bg, --border, …)
// so MUI-rendered surfaces (ChatBox, sidebar) match the app's existing light/dark palette.
const theme = createTheme({
  colorSchemes: {
    light: {
      palette: {
        primary: { main: "#aa3bff" },
        background: { default: "#fff", paper: "#fff" },
        text: { primary: "#08060d", secondary: "#6b6375" },
        divider: "#e5e4e7",
      },
    },
    dark: {
      palette: {
        primary: { main: "#c084fc" },
        background: { default: "#16171d", paper: "#1f2028" },
        text: { primary: "#f3f4f6", secondary: "#9ca3af" },
        divider: "#2e303a",
      },
    },
  },
  typography: {
    fontFamily: "system-ui, 'Segoe UI', Roboto, sans-serif",
  },
  shape: {
    borderRadius: 8,
  },
});

export default theme;
