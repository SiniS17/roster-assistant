"""Print what a roster edit or a daily move WOULD write on both sides. Reads the live sheets, writes nothing.

  python tools/link_dry_run.py --squad 1 --id VAE02591 --date 2026-10-06 --code A864-34
  python tools/link_dry_run.py --squad 2 --id VAE01240 --date 2026-10-06 --n
  python tools/link_dry_run.py --squad 1 --id VAE02591 --date 2026-10-06 --clear
  python tools/link_dry_run.py --squad 1 --id VAE02591 --date 2026-10-06 --tab 6 --to A864-34     (daily move)
  python tools/link_dry_run.py --squad 1 --id VAE02591 --date 2026-10-06 --tab 6 --to ""          (take out)

--squad is 1..4 (the position in config.DISTRIBUTION_SHEET_URLS). Needs the Google credentials (.env).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import assignments  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--squad", type=int, required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--code", help="roster edit: an aircraft code such as A864-34")
    ap.add_argument("--n", action="store_true", help="roster edit: Normal N")
    ap.add_argument("--clear", action="store_true", help="roster edit: empty the cell")
    ap.add_argument("--tab", help="daily move: the day tab")
    ap.add_argument("--to", help="daily move: the section title, UNASSIGNED, or '' to take the person out")
    a = ap.parse_args()
    it = {"squad": a.squad - 1, "id": a.id, "date": a.date}
    if a.tab is not None or a.to is not None:
        it.update(origin="daily", tab=a.tab or "", to=a.to or None)
    elif a.code or a.n or a.clear:
        it.update(origin="roster", kind="code" if a.code else "n" if a.n else "clear", value=a.code or "")
    else:
        ap.error("give --code, --n, --clear (roster edit) or --tab/--to (daily move)")
    res = assignments.dry_run([it])
    print("\n".join(res["lines"]))
    for s in res["squads"]:
        if s["error"]:
            print(f"{s['name']}: {s['error']}")


if __name__ == "__main__":
    main()
