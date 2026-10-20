# User guide

For squad staff and planners. Open the site, then use the **menu** (top-left) to switch pages.

## 1. Roster

The home page shows everyone in the 4 squads in one table, one column per day.

- **Đội** dropdown: show one squad or all.
- **Search**: type part of a name or employee ID.
- **Zoom** (− / +): make the table smaller or larger.
- **Reload** (circular arrow): fetch the latest from Google. Without it, data can be up to 1 minute old.
- **Open Google Sheet** (menu): opens the selected squad's own spreadsheet.
- **Theme** button: light or dark.

Good to know:
- Only people with an employee ID appear. Reinforcement staff (`NV TĂNG CƯỜNG`) are not listed under the squad that borrows them.
- Someone listed in two squads shows once, under the first squad. A note on the page says so.
- If a squad can't be read, a yellow bar names it and the other squads still show.
- Squads with different months show every date; cells are blank where a squad has none.

## 2. Daily Distribution

Menu → **Daily Distribution** (or open `/#distribution`).

1. Pick a squad tab at the top. A `!` badge means that spreadsheet could not be read.
2. Pick a day from the date strip. Today is highlighted.
3. The page shows the day's crew (foreman, trực đội, dock planner, tech support, with phone numbers), then each zone with its people.

Notes:
- Zones with an `@16H00`-style time show a sun/moon icon.
- Structure Sheet Metal, Composite, Painting and Cabin always appear on the right and say "No personnel assigned" until someone is placed there.
- A red remark in the sheet stays red here.
- Use the reload button after someone edits the sheet. A day is otherwise kept for 60 seconds.
- Missing days usually mean the tab name doesn't follow the naming pattern (see below).

**How day tabs must be named** so the page can find them:

| Squad | Tab names |
|---|---|
| Squad 2 and 3 | `B218-SEP21`, `A326-OCT09` (zero-padded days are fine), `WO COMP A611-OCT07` |
| Squad 1 and 4 | just the day number: `1`, `2` ... `31` |

Tabs such as notes or templates that don't match are ignored on purpose.

## 3. KHDT → Roster (training plan)

This marks training days on the roster. It changes the `temp` tab only. `Main` is never touched, so you can review before anything goes live.

1. Menu → **KHDT → Roster**.
2. Choose the KHDT `.xlsx` file.
3. Check the **Roster Google Sheet URL** (pre-filled; change it for another team or month).
4. Tick options if needed:
   - **Overwrite cells that already have content** – only when you are sure. Normally a clash is kept and the new value is added next to it.
   - **Add to the changes already in temp** – tick to keep earlier runs. Unticked, `temp` restarts as a fresh copy of `Main`.
5. Click **Run**.
6. When it finishes:
   - **Download log (.xlsx)** – conflicts, overlaps, name mismatches and skipped rows.
   - **View changes in temp** – see exactly which cells changed.
7. Review `temp`. Copy what you accept into `Main` yourself.

What the markers mean:
- `H ATHK`, `H VHDN CHIỀU`: course short name, with `SÁNG`/`CHIỀU` for half days. Weekday markers are red.
- Saturdays and Sundays always get a black `N` (day off).
- A black `N` is treated as an ordinary day off and is overwritten by a course.
- A red `N` is a protected day off. It is a conflict: the course is added beside it (for example `N-H ATHK`) unless you ticked overwrite.
- A `Lí do` note such as "Lên lớp sáng/chiều <date>" marks that one day only, even if the course spans a week.

Full rules are in `HOW_IT_WORKS.md`.

## Troubleshooting

| What you see | Likely cause | What to do |
|---|---|---|
| A squad is missing from the Roster, or `!` on its Distribution tab | The sheet isn't shared with the service account, or its header row isn't recognised | Share it as Viewer; check the `ID`/`MÃ VAECO` and `NAME`/`HỌ VÀ TÊN` headers and the date row |
| Wrong month on a squad | Its header has day numbers (`01`..`31`) but no real dates, so the current month is assumed | Put real dates in the header, or tell the maintainer |
| A day is missing in Distribution | Tab name doesn't match the patterns above | Rename the tab |
| Crew shows empty | Labels (`FOREMAN:`, `BCH ĐỘI`, `DOCK PLANNER:`) or roster codes (`TĐ`, `PPC`, `FM`) are missing for that day | Add them to the day tab or the roster |
| Changes don't appear | Cache | Press reload |
| KHDT run says it can't find `Main` | The live tab isn't named `Main` | Rename the tab |
| KHDT run logs `[CHECK]` dates | A KHDT date landed outside the roster's month | Check the dates in the KHDT file |
| `DecodeRatioError` | Old build with the httplib2 limit | Update to the latest code |

If something still looks wrong, send the maintainer the error text and the squad/day you were viewing.
