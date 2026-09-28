import { useState } from "react";
import { CssBaseline, List, ListItemButton, ListItemText, Stack, ThemeProvider, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import Button from "@mui/material/Button";
import Chat from "./Chat";
import { createThread, loadThreads, saveThreads, type ThreadSummary } from "./lib/threads";
import theme from "./theme";

function App() {
  const [threads, setThreads] = useState<ThreadSummary[]>(() => {
    const existing = loadThreads();
    if (existing.length > 0) return existing;
    const first = createThread();
    saveThreads([first]);
    return [first];
  });
  const [activeId, setActiveId] = useState(() => threads[0].id);

  function handleNewChat() {
    const thread = createThread();
    setThreads((prev) => {
      const next = [thread, ...prev];
      saveThreads(next);
      return next;
    });
    setActiveId(thread.id);
  }

  function handleThreadUpdate(id: string, patch: Partial<ThreadSummary>) {
    setThreads((prev) => {
      const next = prev.map((thread) =>
        thread.id === id ? { ...thread, ...patch, updatedAt: Date.now() } : thread,
      );
      saveThreads(next);
      return next;
    });
  }

  const sorted = [...threads].sort((a, b) => b.updatedAt - a.updatedAt);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Stack direction="row" sx={{ flex: 1, minHeight: 0 }}>
        <Stack
          component="aside"
          sx={{ width: 220, flexShrink: 0, minHeight: 0, borderRight: 1, borderColor: "divider", p: 1.5, gap: 1.5 }}
        >
          <Button variant="outlined" startIcon={<AddIcon />} onClick={handleNewChat} sx={{ justifyContent: "flex-start" }}>
            Nuevo chat
          </Button>
          <List sx={{ flex: 1, minHeight: 0, overflowY: "auto", py: 0 }}>
            {sorted.map((thread) => (
              <ListItemButton
                key={thread.id}
                selected={thread.id === activeId}
                onClick={() => setActiveId(thread.id)}
                sx={{ borderRadius: 1 }}
              >
                <ListItemText
                  primary={thread.title}
                  slotProps={{ primary: { noWrap: true } }}
                />
              </ListItemButton>
            ))}
          </List>
        </Stack>

        <Stack component="main" sx={{ flex: 1, minWidth: 0, minHeight: 0, px: 2.5 }}>
          <Typography variant="h6" sx={{ my: 2 }}>
            eve • gcs_eevee_assistant
          </Typography>
          <Chat key={activeId} threadId={activeId} onThreadUpdate={handleThreadUpdate} />
        </Stack>
      </Stack>
    </ThemeProvider>
  );
}

export default App;
