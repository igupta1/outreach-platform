"""The Apollo CSV reader: column mapping + light cleaning, no network."""

from __future__ import annotations

import csv

from system_b.prospects import read_apollo_csv, row_from_apollo


def test_row_from_apollo_maps_and_normalizes():
    row = row_from_apollo({
        "First Name": "Dana",
        "Company Name": "Acme LLC",
        "Email": "dana@acme.com",
        "Website": "acme.com",                 # bare domain -> https://
        "City": "Denver",
        "State": "CO",
        "Person Linkedin Url": "https://linkedin.com/in/dana",
    })
    assert row["first_name"] == "Dana"
    assert row["firm_name"] == "Acme LLC"
    assert row["email"] == "dana@acme.com"
    assert row["website"] == "https://acme.com"
    assert row["city"] == "Denver" and row["state"] == "CO"
    assert row["linkedin"] == "https://linkedin.com/in/dana"


def test_row_from_apollo_keeps_scheme_and_company_fallback():
    row = row_from_apollo({
        "Company Name": "",
        "Company Name for Emails": "Beta Inc",
        "Email": "x@beta.io",
        "Website": "http://beta.io/home",
    })
    assert row["firm_name"] == "Beta Inc"
    assert row["website"] == "http://beta.io/home"     # already schemed, untouched


def test_row_from_apollo_drops_rows_missing_website_or_email():
    assert row_from_apollo({"Email": "x@x.com", "Website": ""}) is None
    assert row_from_apollo({"Email": "", "Website": "x.com"}) is None


def test_read_apollo_csv_filters(tmp_path):
    p = tmp_path / "apollo.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["First Name", "Company Name", "Email", "Website"])
        w.writeheader()
        w.writerow({"First Name": "A", "Company Name": "AceCo", "Email": "a@ace.com", "Website": "ace.com"})
        w.writerow({"First Name": "B", "Company Name": "NoSite", "Email": "b@b.com", "Website": ""})
    rows = read_apollo_csv(p)
    assert len(rows) == 1 and rows[0]["firm_name"] == "AceCo"
