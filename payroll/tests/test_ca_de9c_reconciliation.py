from csv import reader
from decimal import Decimal
from io import StringIO
from unittest import TestCase

from report.forms.ca_de9c_reconciliation import compare_filed_de9c, parse_filed_de9c, write_de9c_csv


class CaliforniaDe9cComparisonTests(TestCase):
    def test_equal_quarter_totals_can_hide_employee_discrepancies(self):
        recorded = {
            7: {"pit_wages": Decimal("250.00"), "pit_withheld": Decimal("20.00")},
            8: {"pit_wages": Decimal("150.00"), "pit_withheld": Decimal("15.00")},
        }
        filed = parse_filed_de9c("7,150.00,20.01\n8,250.00,14.99")
        result = compare_filed_de9c(recorded, filed)
        self.assertEqual(result["status"], "Differences found")
        self.assertEqual(result["rows"][0]["wages_difference"], Decimal("-100.00"))
        self.assertEqual(result["rows"][0]["withheld_difference"], Decimal("0.01"))
        self.assertEqual(result["rows"][1]["wages_difference"], Decimal("100.00"))

    def test_missing_and_unexpected_zero_rows_are_reported_separately(self):
        recorded = {7: {"pit_wages": Decimal("0.00"), "pit_withheld": Decimal("0.00")}}
        self.assertEqual(compare_filed_de9c(recorded, None)["status"], "Filed rows needed")
        result = compare_filed_de9c(recorded, parse_filed_de9c("8,0.00,0.00"))
        self.assertEqual([row["status"] for row in result["rows"]], ["Missing from filing", "Unexpected filed row"])

    def test_explicit_no_payroll_is_distinct_from_missing_filing(self):
        self.assertEqual(compare_filed_de9c({}, None)["status"], "Filed rows needed")
        self.assertEqual(compare_filed_de9c({}, parse_filed_de9c("", no_payroll=True))["status"], "Matched")

    def test_filed_employees_without_horilla_ids_remain_visible(self):
        filed = parse_filed_de9c("-,200.00,0.00\n-,130.00,5.00")
        rows = compare_filed_de9c({}, filed)["rows"]
        self.assertEqual([row["status"] for row in rows], ["Unexpected filed row", "Unexpected filed row"])
        self.assertEqual([row["filed_wages"] for row in rows], [Decimal("200.00"), Decimal("130.00")])
        self.assertEqual([row["employee_id"] for row in rows], ["Unassigned row 1", "Unassigned row 2"])

    def test_duplicate_or_malformed_transcriptions_are_rejected(self):
        for value in ("1,2,3\n01,4,5", "1,-2,3", "1,2.004,3", "1,NaN,3", "=123,2,3", "1,2,3,4", "1,2,3,4,Z"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_filed_de9c(value)
        with self.assertRaises(ValueError):
            parse_filed_de9c("")
        with self.assertRaises(ValueError):
            parse_filed_de9c("1,0,0", no_payroll=True)

    def test_csv_preserves_explicit_zeros_and_omits_missing_amounts(self):
        result = compare_filed_de9c({}, parse_filed_de9c("8,0,0"))
        data = list(reader(StringIO(write_de9c_csv(result, employer_id=2, quarter=1))))
        self.assertEqual(data[-1], ["8", "Unexpected filed row", "", "0.00", "", "", "0.00", ""] + [""] * 5)

    def test_subject_wages_and_plan_are_compared_independently_of_pit(self):
        recorded = {7: {"pit_wages": Decimal("100.00"), "pit_withheld": Decimal("2.00")}}
        edd = {7: {"subject_wages": Decimal("120.00"), "plan_code": "S"}}
        result = compare_filed_de9c(recorded, parse_filed_de9c("7,100,2,119,R"), recorded_edd=edd)
        self.assertEqual(result["status"], "Differences found")
        self.assertEqual(result["rows"][0]["subject_wages_difference"], Decimal("-1.00"))
        self.assertEqual(result["rows"][0]["filed_plan_code"], "R")
        self.assertEqual(result["rows"][0]["recorded_plan_code"], "S")
        result = compare_filed_de9c(recorded, parse_filed_de9c("7,100,2,120,R"), recorded_edd=edd)
        self.assertEqual(result["rows"][0]["status"], "Wage plan differs")

    def test_pit_only_entries_and_missing_recorded_edd_facts_have_distinct_coverage(self):
        recorded = {7: {"pit_wages": Decimal("100.00"), "pit_withheld": Decimal("2.00")}}
        result = compare_filed_de9c(recorded, parse_filed_de9c("7,100,2"))
        self.assertEqual(result["status"], "Matched")
        self.assertEqual(result["coverage"], "PIT wages and withholding only")

        result = compare_filed_de9c(recorded, parse_filed_de9c("7,100,2,120,S"))
        self.assertEqual(result["status"], "Recorded EDD fields needed")
        self.assertIsNone(result["rows"][0]["subject_wages_difference"])
