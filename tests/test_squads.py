"""Tests for squads.py on synthetic 1st-sheet grids (no Google access needed).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import squads  # noqa: E402


def serial(y, m, d):
    return (date(y, m, d) - date(1899, 12, 30)).days


HEADER = ["ORD", "NAME AND SURNAME", "ID", "POSITION"]


def grid(rows, dates=()):
    """Header row (with one serial-date column per day) followed by `rows`; padded to a rectangle."""
    header = HEADER + [serial(*d) for d in dates]
    out = [["A/C", "B218"], header] + [list(r) for r in rows]
    width = max(len(r) for r in out)
    return [(r + [None] * width)[:width] for r in out]


class ExtractMembers(unittest.TestCase):
    def test_stops_at_tang_cuong_row(self):
        values = grid([
            [1, "An", "VAE001", "B1"],
            [2, "Binh", "VAE002", "B1"],
            ["", "TĂNG CƯỜNG"],
            [3, "Chi", "VAE003", "B2"],
        ])
        self.assertEqual([m["id"] for m in squads.extract_squad_members(values)], ["VAE001", "VAE002"])

    def test_label_match_ignores_accents_case_and_spacing(self):
        values = grid([[1, "An", "VAE001"], ["", "  tang   CUONG "], [2, "Binh", "VAE002"]])
        self.assertEqual([m["id"] for m in squads.extract_squad_members(values)], ["VAE001"])

    def test_stops_when_ord_ends_without_a_marker(self):
        values = grid([
            [1, "An", "VAE001"],
            [2, "Binh", "VAE002"],
            ["", "", ""],
            ["", "Chi", "VAE003"],
        ])
        self.assertEqual([m["id"] for m in squads.extract_squad_members(values)], ["VAE001", "VAE002"])

    def test_stops_when_ord_starts_over(self):
        values = grid([
            [1, "An", "VAE001"],
            [2, "Binh", "VAE002"],
            [1, "Chi", "VAE003"],
        ])
        self.assertEqual([m["id"] for m in squads.extract_squad_members(values)], ["VAE001", "VAE002"])

    def test_marker_in_a_members_remark_does_not_end_the_list(self):
        values = grid([
            [1, "An", "VAE001", "tăng cường từ đội 2"],
            [2, "Binh", "VAE002", "B1"],
        ])
        self.assertEqual([m["id"] for m in squads.extract_squad_members(values)], ["VAE001", "VAE002"])

    def test_numbered_empty_slot_is_skipped_but_list_continues(self):
        values = grid([
            [1, "An", "VAE001"],
            [2, "", ""],
            [3, "Chi", "VAE003"],
        ])
        self.assertEqual([m["id"] for m in squads.extract_squad_members(values)], ["VAE001", "VAE003"])

    def test_ids_are_normalised_and_rows_are_reported(self):
        values = grid([[1, "An", " vae001 "]])
        (m,) = squads.extract_squad_members(values)
        self.assertEqual((m["id"], m["name"], m["row"]), ("VAE001", "An", 2))

    def test_works_when_the_sheet_has_no_day_columns(self):
        values = grid([[1, "An", "VAE001"], [2, "Binh", "VAE002"], ["", "TĂNG CƯỜNG"], [3, "Chi", "VAE003"]])
        self.assertEqual([m["id"] for m in squads.extract_squad_members(values)], ["VAE001", "VAE002"])

    def test_no_header_is_an_error(self):
        with self.assertRaises(ValueError):
            squads.extract_squad_members([["hello", "world"]])


class Combine(unittest.TestCase):
    def test_lowest_numbered_squad_wins(self):
        a = {"id": "VAE001", "name": "An", "row": 2, "ord": 1}
        b = {"id": "VAE002", "name": "Binh", "row": 3, "ord": 2}
        people, conflicts, dups = squads.combine_squads([
            ("Squad 1", [a]),
            ("Squad 2", [b, {**a, "row": 9}]),
            ("Squad 3", [{**a, "row": 4}, {**b, "row": 5}]),
        ])
        self.assertEqual([(p["id"], p["squad"]) for p in people], [("VAE001", "Squad 1"), ("VAE002", "Squad 2")])
        self.assertEqual(
            sorted((c["id"], c["kept"], tuple(c["dropped"])) for c in conflicts),
            [("VAE001", "Squad 1", ("Squad 2", "Squad 3")), ("VAE002", "Squad 2", ("Squad 3",))],
        )
        self.assertEqual(dups, {})

    def test_same_person_twice_in_one_squad_is_a_duplicate_not_a_conflict(self):
        a = {"id": "VAE001", "name": "An", "row": 2, "ord": 1}
        people, conflicts, dups = squads.combine_squads([("Squad 1", [a, {**a, "row": 3}])])
        self.assertEqual(len(people), 1)
        self.assertEqual(conflicts, [])
        self.assertEqual(dups, {"Squad 1": 1})

    def test_people_without_id_are_matched_by_name(self):
        x = {"id": "", "name": "Nguyễn Văn A", "row": 2, "ord": 1}
        people, conflicts, _ = squads.combine_squads([("Squad 1", [x]), ("Squad 2", [{**x, "name": "nguyen van a"}])])
        self.assertEqual(len(people), 1)
        self.assertEqual(len(conflicts), 1)


class BuildPayload(unittest.TestCase):
    def build(self, grids, urls=None):
        names = [f"Squad {i}" for i in range(1, len(grids) + 1)]
        squad_list = [(n, f"https://example.test/{i}") for i, n in enumerate(names, 1)]

        def fake_first_sheet_grid(index, force=False):
            if isinstance(grids[index], Exception):
                raise grids[index]
            values = grids[index]
            return "Sheet1", values, [[None] * len(r) for r in values]

        with mock.patch.object(squads, "configured_squads", return_value=squad_list), \
                mock.patch.object(squads, "first_sheet_grid", side_effect=fake_first_sheet_grid):
            return squads.build_squads_payload()

    def test_combines_squads_with_priority_and_one_date_axis(self):
        s1 = grid([
            [1, "An", "VAE001", "B1", "N", "", "H ATHK"],
            [2, "Binh", "VAE002", "B1", "", "N", ""],
            ["", "TĂNG CƯỜNG"],
            [3, "Chi", "VAE003", "B2", "X", "X", "X"],
        ], dates=[(2026, 10, 1), (2026, 10, 2), (2026, 10, 3)])
        s2 = grid([
            [1, "An (copy)", "VAE001", "B1", "Z", "Z", "Z"],  # also in Squad 1 -> dropped here
            [2, "Chi", "VAE003", "B2", "", "N", "N"],         # only listed as reinforcement in squad 1 -> kept here
        ], dates=[(2026, 10, 2), (2026, 10, 3), (2026, 10, 4)])
        p = self.build([s1, s2])

        self.assertEqual(p["dates"], ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"])
        self.assertEqual([(e["id"], e["squad"]) for e in p["employees"]],
                         [("VAE001", "Squad 1"), ("VAE002", "Squad 1"), ("VAE003", "Squad 2")])
        by_id = {e["id"]: e for e in p["employees"]}
        self.assertEqual(by_id["VAE001"]["cells"], ["N", "", "H ATHK", ""])
        self.assertEqual(by_id["VAE003"]["cells"], ["", "", "N", "N"])  # Squad 2's own days, on the shared axis
        self.assertEqual(by_id["VAE001"]["name"], "An")
        self.assertEqual(p["info_headers"], ["Squad", "POSITION"])
        self.assertEqual(by_id["VAE003"]["info"], ["Squad 2", "B2"])
        self.assertEqual(p["view"], "squads")
        self.assertEqual([(s["name"], s["members"]) for s in p["squads"]], [("Squad 1", 2), ("Squad 2", 2)])
        self.assertEqual([(c["id"], c["kept"], c["dropped"]) for c in p["conflicts"]], [("VAE001", "Squad 1", ["Squad 2"])])
        self.assertTrue(any("more than one squad" in n for n in p["notes"]))

    def test_one_unreadable_squad_does_not_hide_the_others(self):
        s1 = grid([[1, "An", "VAE001", "B1", "N"]], dates=[(2026, 10, 1)])
        p = self.build([s1, PermissionError("not shared with the service account")])
        self.assertEqual([e["id"] for e in p["employees"]], ["VAE001"])
        self.assertTrue(any("Squad 2 couldn't be read" in n for n in p["notes"]))

    def test_every_squad_unreadable_is_an_error(self):
        with self.assertRaises(ValueError):
            self.build([RuntimeError("a"), RuntimeError("b")])

    def test_squad_without_day_columns_still_lists_its_members(self):
        s1 = grid([[1, "An", "VAE001", "B1", "N"]], dates=[(2026, 10, 1)])
        s2 = grid([[1, "Binh", "VAE002", "B1"]])  # no date columns at all
        p = self.build([s1, s2])
        self.assertEqual([e["id"] for e in p["employees"]], ["VAE001", "VAE002"])
        self.assertEqual({e["id"]: e["cells"] for e in p["employees"]}["VAE002"], [""])
        self.assertTrue(any("no day columns" in n for n in p["notes"]))


if __name__ == "__main__":
    unittest.main()
