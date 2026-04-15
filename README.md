# LLM Visibility Dashboard

Internal web app for the team to run on-demand brand-visibility audits across
ChatGPT, Claude, Gemini, Grok, and Perplexity — anchored to a specific
country / state / city.

Independent of the parent `visibility_audit2.0.py` script. Reads the same
`.env` (one level up) for API keys; results are stored in its own SQLite DB
under `dashboard/data/audits.db`.

## Setup

```bash
cd dashboard
pip install -r requirements.txt
```

API keys come from `../.env` (the same file the parent script uses) — set any
of `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY`,
`PERPLEXITY_API_KEY`. LLMs without a key show as disabled in the UI.

## Run (locally)

```bash
python app.py
```

Then open <http://localhost:8000>.

## Deploy (Oracle Cloud Always Free)

See [DEPLOY.md](./DEPLOY.md) for a 30-minute walkthrough that puts this on a
free-forever VM with a shared-password login. After that, the team just opens
a URL.

## Pages

- `/` — new audit form (queries, location pickers, LLM checkboxes)
- `/history` — every audit run from this dashboard
- `/results/{id}` — live progress + final breakdown for an audit

## Notes

- Audits run in a background thread; the results page polls every 3s.
- A query line prefixed with `[Intent Name]` groups it under that intent.
- "Save Set" stores reusable query lists (deduped by name).
- All location options are bundled in `locations.json` — USA gets all 50
  states; California has the most cities. A handful of other countries are
  included.
- This dashboard does **not** touch the parent `archives/` folder; data is
  kept separate in `dashboard/data/`.
