# Roster Assistant

An internal VAECO web tool (Flask + Google Sheets) for line-maintenance squads. It does three things:

| Feature | What it does | Access it needs |
|---|---|---|
| **Roster** (`/`) | One combined, searchable roster of the 4 squads, with a squad (Đội) filter | Viewer |
| **Daily Distribution** (`/#distribution`) | Shows who is in which zone on a chosen day, plus the day's crew (foreman, trực đội, dock planner) | Viewer |
| **KHDT → Roster** | Reads the monthly training plan (KHDT `.xlsx`) and marks training days in the roster's `temp` tab | Editor, on the KHDT roster sheet only |

Everything the website reads from Google is read-only, except the KHDT run, which writes to a `temp` tab and never to `Main`.

## Quick start

```bash
git clone https://github.com/SiniS17/roster-assistant.git
cd roster-assistant
pip install -r requirements.txt
```

Create a `.env` file in the project root (it is gitignored):

```
GOOGLE_APPLICATION_CREDENTIALS=./path/to/service-account-key.json
FLASK_SECRET_KEY=any-long-random-string
```

Then run:

```bash
python app.py
```

Open http://localhost:5000.

Hosted setups can use `GOOGLE_SERVICE_ACCOUNT_JSON` (the whole key as one line) instead of the key file. `PORT` changes the port (default 5000).

## Google access

The app signs in as a Google **service account**, not as a person. For anything to load:

1. Enable the **Google Sheets API** in the service account's Google Cloud project.
2. Share each squad spreadsheet with the service account's email as **Viewer**.
3. Share the KHDT roster sheet (`DEFAULT_ROSTER_SHEET_URL`) as **Editor**.
4. Enable the **Google Drive API** only if a squad file is an uploaded `.xlsx` opened in Google Sheets.

The bot email is noted at the bottom of `config.py`.

## Configuration

All settings are in `config.py`. Don't hardcode sheet URLs anywhere else.

- `DISTRIBUTION_SHEET_URLS` – the 4 squad spreadsheets (1st URL = Squad 1 ... last = Squad 4). The environment variable of the same name overrides it.
- `DISTRIBUTION_SHEET_NAMES` – display names, matched by position.
- `DISTRIBUTION_ROLE_MARKERS` – roster codes for crew roles (`TĐ`, `ppc`, `fm`).
- `DEFAULT_ROSTER_SHEET_URL` – the KHDT sheet with its `Main` and `temp` tabs.
- `COURSE_ABBREVIATIONS`, `COURSE_NAME_ABBREVIATIONS`, `MARKER_PREFIX` – marker text such as `H ATHK`.
- `DISTRIBUTION_CACHE_SECONDS` – server cache (60 s). The reload button always bypasses it.

## Tests

```bash
pip install pytest "httplib2>=0.32"
python -m pytest tests
```

The tests use fake Google data and need no network or credentials. `httplib2` 0.32 or newer is required by the HTTP-limit test.

## Documentation

- [`guide.md`](guide.md) – how to use the website, and what to do when something looks wrong.
- [`structure.md`](structure.md) – how the code is organised, for developers.
- [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md) – the exact marking rules and the sheet layouts the tool expects.
- [`CLAUDE.md`](CLAUDE.md) – session-by-session handover notes and open items.
