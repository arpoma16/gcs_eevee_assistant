import { disableTool } from "eve/tools";

// web_search es una tool provider-defined. Gemini no soporta combinarlas con
// function tools ("combination of function and provider-defined tools is not
// supported"), y su presencia rompe TODO el tool calling del agente.
// El agente opera contra el GCS, no contra la web: no la necesita.
export default disableTool();
