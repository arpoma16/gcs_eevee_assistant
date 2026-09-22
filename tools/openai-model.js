
const key = process.env.OPENAI_API_KEY;
if (!key) { console.error("NO OPENAI_API_KEY in env"); process.exit(1); }
fetch("https://api.openai.com/v1/models", { headers: { Authorization: `Bearer ${key}` } })
  .then(r => r.json())
  .then(d => {
    const ids = (d.data || []).map(m => m.id).filter(id => id.includes("gpt-5")).sort();
    console.log(ids.join("\n"));
  })
  .catch(e => console.error(e))