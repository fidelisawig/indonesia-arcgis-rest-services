#!/usr/bin/env python3

import concurrent.futures
import json
from datetime import datetime

import pandas as pd
import requests

# ==========================
# Configuration
# ==========================

TIMEOUT = (5, 15)          # (connect timeout, read timeout)
MAX_WORKERS = 12

# ==========================
# Helper Functions
# ==========================

def request_json(url):
    """
    Request an ArcGIS REST endpoint and return:
    (HTTP Status, Response Time (ms), JSON object)

    Raises exceptions if the endpoint cannot be parsed.
    """

    response = requests.get(
        url.rstrip("/"),
        params={"f": "pjson"},
        timeout=TIMEOUT,
        headers={
            "User-Agent": "indonesia-arcgis-rest-services-checker"
        },
    )

    elapsed = round(response.elapsed.total_seconds() * 1000)

    content_type = response.headers.get("Content-Type", "")

    if "json" not in content_type.lower():
        raise ValueError("Response is not JSON")

    try:
        data = response.json()

    except json.JSONDecodeError:
        raise ValueError("Invalid JSON")

    return response.status_code, elapsed, data


# ==========================
# Inspect One Endpoint
# ==========================

def inspect(row):

    endpoint = row.URL.rstrip("/")

    result = {
        "Institution": row.Institution,
        "Name": row.Name,
        "URL": endpoint,
        "Status": "❌ Offline",
        "HTTP": "-",
        "Response": "-",
        "Folders": "-",
        "Services": "-",
        "Layers": "-",
    }

    try:

        http, elapsed, j = request_json(endpoint)

        result["HTTP"] = http
        result["Response"] = elapsed

        if http != 200:
            return result

        if "error" in j:
            result["Status"] = "⚠️ ArcGIS Error"
            return result

        result["Status"] = "✅ Online"

        result["Folders"] = len(j.get("folders", []))
        result["Services"] = len(j.get("services", []))
        result["Layers"] = len(j.get("layers", []))

    except requests.exceptions.Timeout:

        result["Status"] = "⌛ Timeout"

    except requests.exceptions.ConnectionError:

        result["Status"] = "❌ Connection Error"

    except ValueError as e:

        if str(e) == "Response is not JSON":
            result["Status"] = "⚠️ Response is not JSON"
        else:
            result["Status"] = "⚠️ Invalid JSON"

    except Exception:

        result["Status"] = "❌ Failed"

    return result


# ==========================
# Main
# ==========================

catalog = pd.read_csv("data/services.csv")

results = []

with concurrent.futures.ThreadPoolExecutor(
    max_workers=MAX_WORKERS
) as executor:

    futures = [
        executor.submit(inspect, row)
        for row in catalog.itertuples(index=False)
    ]

    for future in concurrent.futures.as_completed(futures):

        result = future.result()

        print(
            f"{result['Status']:18}"
            f"{str(result['HTTP']):>5} "
            f"{result['Institution']:<20}"
            f"{result['Name']}"
        )

        results.append(result)

# Sort output
results.sort(
    key=lambda r: (
        r["Institution"],
        r["Name"],
    )
)

# ==========================
# Write Markdown Report
# ==========================

today = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

with open(
    "status/services_status.md",
    "w",
    encoding="utf-8",
) as f:

    f.write("# ArcGIS REST Service Status\n\n")

    f.write(
        "This report is generated automatically by GitHub Actions.\n\n"
    )

    f.write(f"**Last checked:** {today}\n\n")

    f.write(
        "| Institution | Service | Status | HTTP | Response (ms) | Folders | Services | Layers |\n"
    )

    f.write(
        "|---|---|:---:|---:|---:|---:|---:|---:|\n"
    )

    for r in results:

        f.write(
            f"| {r['Institution']} "
            f"| {r['Name']} "
            f"| {r['Status']} "
            f"| {r['HTTP']} "
            f"| {r['Response']} "
            f"| {r['Folders']} "
            f"| {r['Services']} "
            f"| {r['Layers']} |\n"
        )

print("\nFinished.")
print("Report written to status/services_status.md")