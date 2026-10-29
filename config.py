"""User-editable labels for roster markers and the Excel log."""

# ------------------------------------------------------------
# Google Sheet used by the KHDT -> Roster upload only (its Main and temp tabs). Pre-fills the
# KHDT form; users can still paste a different sheet URL for a different team/month.
# The roster page itself no longer reads this sheet: it is built from the 1st sheet of each
# squad's spreadsheet listed in DISTRIBUTION_SHEET_URLS below.
# ------------------------------------------------------------
DEFAULT_ROSTER_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/16cIg2Ufh3FO8Qt6KC7WGzP9NcppfiRziCtsHigVt-T4/edit?hl=vi&pli=1&gid=0#gid=0"
)

# ------------------------------------------------------------
# Daily Distribution page: the spreadsheets it reads (view-only).
# Share each one with the service-account email as *Viewer*.
# Add as many as you need - one line per spreadsheet. You can also set the
# DISTRIBUTION_SHEET_URLS environment variable (one URL per line, or comma
# separated); when set, it replaces this list.
# ------------------------------------------------------------
import os as _os

DISTRIBUTION_SHEET_URLS = [
    "https://docs.google.com/spreadsheets/d/1YH2jSX-QdcuEwL7b8xsqhp9QqiuPGe8aJd96IBFtIHo/edit?gid=2076737416#gid=2076737416",
    "https://docs.google.com/spreadsheets/d/1sCP1udfS6UWh-YW-hV5Ruhw4zeZhtIrfE1CPTcmAYVY/edit?gid=1860011037#gid=1860011037",
    "https://docs.google.com/spreadsheets/d/1r1LwVdHPIKW0y2L4qpTGzIatYGKXHU8Mr_KP-i5XL4s/edit?usp=drivesdk",
    "https://docs.google.com/spreadsheets/d/1yPaJLNurDRcUAaV7gaoBaSHA8xe3F7S-Vm1gjr6ktUM/edit?gid=517121129#gid=517121129",
]
_env_urls = _os.environ.get("DISTRIBUTION_SHEET_URLS", "").strip()
if _env_urls:
    DISTRIBUTION_SHEET_URLS = [u.strip() for u in _env_urls.replace(",", "\n").splitlines() if u.strip()]

# Display name of each spreadsheet above, matched BY POSITION: the 1st URL is
# Squad 1, the last one is Squad 4. Shown on the Daily Distribution tabs.
# If you add a URL and forget a name, it falls back to "Squad <position>".
DISTRIBUTION_SHEET_NAMES = [
    "Squad 1",
    "Squad 2",
    "Squad 3",
    "Squad 4",
]

# Daily Distribution crew role -> the code used for that role in the main roster.
#   Trực đội -> TĐ,  Dock planner -> ppc,  Foreman -> fm
# Keys match the labels read from each spreadsheet's 1st sheet.
DISTRIBUTION_ROLE_MARKERS = {
    "truc_doi": "TĐ",
    "dock_planner": "ppc",
    "foreman": "fm",
}

# Roster <-> Daily Distribution link (assignments.py, Phase 3: dry-run only, nothing is written).
# How each squad's roster cell relates to its day tab, matched BY POSITION like the names above:
#   "zone"     - the roster cell holds aircraft + zone ('A864-34') and the day tab has a section with that
#                same title (Squads 1 and 4; day tabs are named '1', '2' ...).
#   "aircraft" - the roster cell holds the aircraft only ('A611'); the zone exists only on the day tab
#                ('ZONE 128' on tab 'A611-OCT06') (Squads 2 and 3).
DISTRIBUTION_SQUAD_LAYOUTS = ["zone", "aircraft", "aircraft", "zone"]

# Section a person is placed in when the roster gives an aircraft but no zone (created at the bottom of
# a table on the day tab if it does not exist yet).
LINK_UNASSIGNED_TITLE = "UNASSIGNED"

# When somebody is taken out of the Daily Distribution on purpose (not moved to another zone): False = the
# roster cell is left as it is, True = it is cleared. (The plan left this open; False loses nothing.)
LINK_REMOVE_CLEARS_ROSTER = False

# What the edit functions write on the day side (assignments.commit, Phase 4):
#   "database" - one flat tab per aircraft and day, named like 'A123-OCT29': row 1 = Name | VAEID | Function |
#                Zone | remark, one person per row from row 2 (daily_db.py). The tab is created when missing.
#                Hand-made day tabs are only read, never written.
#   "legacy"   - fill the hand-made day tabs cell by cell (the Phase 3 dry-run plans; commit refuses them).
DAILY_WRITE_FORMAT = "database"

# How long (seconds) fetched sheet data is reused before asking Google again.
# The page's reload button always bypasses this.
DISTRIBUTION_CACHE_SECONDS = 60

# Prefix written in front of every course marker.
MARKER_PREFIX = "H"

# Class-code prefix (the part before the last two "/"-separated segments)
# mapped to the short label used in the roster.
COURSE_ABBREVIATIONS = {
    "ATHK": "ATHK",
    "VHNT-GD2": "VHNT",
    "VHDN-VAE": "VHDN",
    "AMOS-LB": "AMOS",
    "EWIS-ADV-I": "EWIS",
    "A320/321-B12-P": "CL321 PRAC",
}

# Full course names mapped to short labels when the class-code field is empty.
# Matching ignores accents, case, and repeated spaces.
COURSE_NAME_ABBREVIATIONS = {
    "Lớp 3 – INS-COA/2603/S - Thực hành nhóm 1": "INS-COA G1",
    "Lớp 3 – INS-COA/2603/S - Thực hành nhóm 2": "INS-COA G2",
    "Cập nhật chính sách mới về thuế và kế toán,": "CN THUẾ KT",
    "Văn hóa doanh nghiệp VAECO": "VHDN",
    "Đào tạo, huấn luyện định kỳ - Vận hành thiết bị điều hòa không khí": "ĐT ĐỊNH KỲ ĐHKK",
    "EASA MTOE": "EASA MTOE",
    "EWIS (Electrical Wiring Interconnection Systems) - Advanced Initial Training": "EWIS ADV",
    "A320/321 (CFM56/V2500) To A320/321 (PW1100G) Aircraft Maintenance Difference Course - Theoretical Part": "CL321 NEO THEO",
    "A320/321 (CFM56/V2500) To A320/321 (PW1100G) Aircraft Maintenance Difference Course - Practical Part": "CL321 NEO PRAC",
    "Type Training - A320/321 (CFM56/V2500) Cat B1+B2 - Theoretical Part": "CL321 THEO",
    "Supplement Practical Basic for completing section 4 - Knowledge and Skill Training - CAT B1": "SECTION 4",
    "An toàn hàng không": "ATHK",
    "Human Factor Continuation Training for EASA Roster": "HF CONT EASA",
}

# Change these values if the log should use another language or terminology.
# In particular, LOG_COLUMN_HEADERS["event"] controls the "Event" column name.
LOG_COLUMN_HEADERS = {
    "name": "Name",
    "id": "ID",
    "date": "Date",
    "event": "Event",
    "reason": "Reason",
    "details": "Details",
}

LOG_EVENT_LABELS = {
    "note": "Đã xếp lịch",
    "conflict": "Có lịch đi làm",
    "overlap": "Nhiều lớp",
    "overwrite_day_off": "Học trùng N đen",
    "guarantee_day_off_conflict": "Học trùng N đỏ",
    "name_mismatch": "Sai tên",
    "skipped": "Bỏ qua",
    "no_date_overlap": "Ngoài khoảng ngày",
    "already_marked": "Đã có sẵn, bỏ qua",
}

# bot email:khdt-roster-bot@khdt-roster.iam.gserviceaccount.com

# Roster editor: what is UNTOUCHABLE while editing. One place for the page (it gets this dict) and the server
# (roster_edit.lock_reason). A cell matching any rule cannot be overwritten, cleared or pasted over by hand.
ROSTER_LOCKED = {
    # KHDT course markers ('H ATHK' ...): KHDT owns them. True = locked.
    "course_marker": True,
    # Red N (forced day off): "bulk" = locked when the action covers several cells (a drag over more than one
    # cell, or a paste that fills several) but a single click on one cell can still change it;
    # "always" = never editable by hand; "never" = always editable.
    "red_n": "bulk",
    # A cell whose text STARTS with one of these (case-insensitive) is locked, e.g. "LINE", "LINE 2", "line-A864".
    "prefixes": ["LINE"],
}
