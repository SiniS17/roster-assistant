"""User-editable labels for roster markers and the Excel log."""

# ------------------------------------------------------------
# Squad spreadsheets (view-only). There is no single "everyone in one sheet"
# roster any more: each squad keeps its own spreadsheet, and
#   - the Roster page is built from the 1st sheet of every squad
#     (members = the rows from the top of the list until a "tăng cường" row
#     or the first end of the ORD numbering),
#   - the Daily Distribution page reads the day tabs of the same spreadsheets.
#
# ORDER MATTERS: if the same person is listed in more than one squad, they
# stay in the lowest-numbered squad (Squad 1 wins over 2, 2 over 3, 3 over 4).
#
# Share each spreadsheet with the service-account email as *Viewer*.
# You can also set the SQUAD_SHEET_URLS environment variable (one URL per
# line, or comma separated, in squad order: first = Squad 1, ...); when set it
# replaces this list. The old DISTRIBUTION_SHEET_URLS variable still works.
# ------------------------------------------------------------
import os as _os

SQUAD_SHEET_URLS = {
    "Squad 1": "https://docs.google.com/spreadsheets/d/1YH2jSX-QdcuEwL7b8xsqhp9QqiuPGe8aJd96IBFtIHo/edit?gid=2076737416#gid=2076737416",
    "Squad 2": "https://docs.google.com/spreadsheets/d/1sCP1udfS6UWh-YW-hV5Ruhw4zeZhtIrfE1CPTcmAYVY/edit?gid=1860011037#gid=1860011037",
    "Squad 3": "https://docs.google.com/spreadsheets/d/1r1LwVdHPIKW0y2L4qpTGzIatYGKXHU8Mr_KP-i5XL4s/edit?gid=865448519#gid=865448519",
    "Squad 4": "https://docs.google.com/spreadsheets/d/1yPaJLNurDRcUAaV7gaoBaSHA8xe3F7S-Vm1gjr6ktUM/edit?gid=517121129#gid=517121129",
}
_env_urls = (_os.environ.get("SQUAD_SHEET_URLS") or _os.environ.get("DISTRIBUTION_SHEET_URLS") or "").strip()
if _env_urls:
    SQUAD_SHEET_URLS = {
        f"Squad {i}": u.strip()
        for i, u in enumerate((u for u in _env_urls.replace(",", "\n").splitlines() if u.strip()), start=1)
    }

# The text that ends a squad's own member list on the 1st sheet (matched
# ignoring accents, case and extra spaces, so "TĂNG CƯỜNG" also matches).
SQUAD_MEMBER_STOP_LABEL = "tăng cường"

# ------------------------------------------------------------
# Daily Distribution crew (the strip above the zones). It is NOT typed on the
# Daily Distribution page: for the chosen day, anyone in that squad whose
# ROSTER cell for that day contains the code holds the role. The code is
# matched as its own word, ignoring accents and case (so "TĐ" also matches "td"
# and "TĐ - ATHK", but not "FMX"). Several people can hold one role.
#   key = role (do not rename the keys), value = the roster code.
# "Shift / Tech supp" is not in this list: it still comes from the label on the
# squad's 1st sheet.
# ------------------------------------------------------------
CREW_ROSTER_CODES = {
    "truc_doi": "TĐ",        # Trực đội  = anyone with TĐ in the roster that day
    "foreman": "FM",         # Foreman   = anyone with FM in the roster that day
    "dock_planner": "PPC",   # Dock planner = anyone with PPC in the roster that day
}

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
