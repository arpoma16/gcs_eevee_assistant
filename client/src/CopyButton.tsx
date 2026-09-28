import { useState } from "react";
import Button from "@mui/material/Button";

interface CopyButtonProps {
  text: string;
  label?: string;
}

/** Small "copy to clipboard" affordance, used for session ids the operator needs verbatim (e.g. for `docker ps --filter label=...` or `eve traces`) — copy-paste errors there just produce silent empty results, not an error message. */
function CopyButton({ text, label = "Copiar" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  async function handleClick() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API unavailable (insecure context, permissions) — nothing to fall back to silently.
    }
  }

  return (
    <Button size="small" onClick={() => void handleClick()} title={text}>
      {copied ? "✓ copiado" : label}
    </Button>
  );
}

export default CopyButton;
