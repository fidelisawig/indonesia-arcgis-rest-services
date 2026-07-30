#!/usr/bin/env python3
"""
ArcGIS REST Services Status & Deep Crawler

Performs a comprehensive recursive crawl of ArcGIS REST Services cataloged in data/services.csv:
- Measures HTTP status code & response time (ms)
- Recursively visits all root and nested subfolders
- Discovers all services published under endpoints/folders
- Counts MapServer, FeatureServer, ImageServer, and other service types
- Inspects service endpoints to count total layers across all services
- Outputs summary to console and writes unified report to status/services_status.md
"""

import concurrent.futures
import csv
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ==========================
# Configuration
# ==========================

TIMEOUT = 12
MAX_WORKERS = 10
HEADERS = {
    "User-Agent": "indonesia-arcgis-rest-services-checker"
}

# SSL Context to bypass self-signed / invalid SSL certificates
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


# ==========================
# Helper Functions
# ==========================

def fetch_json(url):
    """
    Fetch ArcGIS REST endpoint with JSON parameter using urllib.
    Returns (elapsed_ms, json_dict) or raises Exception.
    """
    url_clean = url.rstrip("/")
    target_url = f"{url_clean}?f=pjson"
    req = urllib.request.Request(target_url, headers=HEADERS)

    start_time = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl_context) as response:
            elapsed_ms = round((time.time() - start_time) * 1000)
            if response.status != 200:
                raise ValueError(f"HTTP {response.status}")

            raw_data = response.read().decode("utf-8", errors="ignore")
            content_type = response.headers.get("Content-Type", "")

            if "json" not in content_type.lower() and not raw_data.strip().startswith("{"):
                raise ValueError("Response is not JSON")

            data = json.loads(raw_data)

            if "error" in data:
                err_msg = data["error"].get("message", "ArcGIS REST Error")
                raise ValueError(f"ArcGIS Error: {err_msg}")

            return elapsed_ms, data
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise TimeoutError("Timeout")
        raise e


def inspect_service_layers(root_url, service_item):
    """
    Given service_item dict (with 'name' and 'type'), fetch service metadata to count layers.
    Returns layer count (int).
    """
    s_name = service_item.get("name", "")
    s_type = service_item.get("type", "")
    if not s_name or not s_type:
        return 0

    service_url = f"{root_url.rstrip('/')}/{s_name}/{s_type}"
    try:
        _, data = fetch_json(service_url)
        layers = data.get("layers", [])
        return len(layers)
    except Exception:
        return 0


# ==========================
# Single Unified Endpoint Inspection
# ==========================

def inspect_endpoint(row):
    """
    Inspects a single catalog endpoint:
    - Measures HTTP status & response time
    - Recursively crawls folders
    - Discovers services and service types
    - Inspects total layers
    """
    root_url = row.URL.rstrip("/")

    summary = {
        "Institution": row.Institution,
        "Name": row.Name,
        "URL": root_url,
        "Status": "❌ Offline",
        "HTTP": "-",
        "Response": "-",
        "Folders": 0,
        "TotalServices": 0,
        "MapServer": 0,
        "FeatureServer": 0,
        "ImageServer": 0,
        "OtherServer": 0,
        "TotalLayers": 0,
    }

    try:
        elapsed_ms, root_data = fetch_json(root_url)
        summary["Status"] = "✅ Online"
        summary["HTTP"] = 200
        summary["Response"] = elapsed_ms
    except TimeoutError:
        summary["Status"] = "⌛ Timeout"
        return summary
    except urllib.error.URLError as e:
        summary["Status"] = "❌ Connection Error"
        return summary
    except ValueError as e:
        if str(e) == "Response is not JSON":
            summary["Status"] = "⚠️ Response is not JSON"
        elif "ArcGIS Error" in str(e):
            summary["Status"] = "⚠️ ArcGIS Error"
        else:
            summary["Status"] = "⚠️ Invalid JSON"
        return summary
    except Exception:
        summary["Status"] = "⚠️ Failure"
        return summary

    # Deep Crawl Folders
    folders_to_crawl = list(root_data.get("folders", []))
    summary["Folders"] = len(folders_to_crawl)

    discovered_services = list(root_data.get("services", []))

    visited_folders = set()
    while folders_to_crawl:
        folder = folders_to_crawl.pop(0)
        if folder in visited_folders:
            continue
        visited_folders.add(folder)

        folder_url = f"{root_url}/{folder}"
        try:
            _, folder_data = fetch_json(folder_url)
            subfolders = folder_data.get("folders", [])
            for sub in subfolders:
                full_sub_path = f"{folder}/{sub}"
                if full_sub_path not in visited_folders:
                    folders_to_crawl.append(full_sub_path)

            discovered_services.extend(folder_data.get("services", []))
        except Exception:
            pass

    summary["Folders"] = len(visited_folders)
    summary["TotalServices"] = len(discovered_services)

    # Classify service types
    for s in discovered_services:
        stype = s.get("type", "").lower()
        if stype == "mapserver":
            summary["MapServer"] += 1
        elif stype == "featureserver":
            summary["FeatureServer"] += 1
        elif stype == "imageserver":
            summary["ImageServer"] += 1
        else:
            summary["OtherServer"] += 1

    # Fetch layer counts concurrently across services
    total_layers = 0
    if discovered_services:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as s_executor:
            futures = [
                s_executor.submit(inspect_service_layers, root_url, s)
                for s in discovered_services
            ]
            for f in concurrent.futures.as_completed(futures):
                total_layers += f.result()

    summary["TotalLayers"] = total_layers
    return summary


# ==========================
# Main Script Execution
# ==========================

def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    catalog_path = "data/services.csv"
    if not os.path.exists(catalog_path):
        print(f"Error: {catalog_path} not found.")
        sys.exit(1)

    print("Starting Unified ArcGIS REST Services Check & Crawl...")
    with open(catalog_path, mode="r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    class Row:
        def __init__(self, d):
            self.Institution = d.get("Institution", "")
            self.Name = d.get("Name", "")
            self.URL = d.get("URL", "")

    catalog_rows = [Row(r) for r in reader]
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(inspect_endpoint, row)
            for row in catalog_rows
        ]

        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            print(
                f"{res['Status']:22} | "
                f"HTTP: {str(res['HTTP']):>3} | "
                f"Response: {str(res['Response']):>4} ms | "
                f"Folders: {res['Folders']:>3} | "
                f"Services: {res['TotalServices']:>4} (Map: {res['MapServer']}, Feature: {res['FeatureServer']}, Image: {res['ImageServer']}) | "
                f"Layers: {res['TotalLayers']:>5} | "
                f"{res['Institution']} - {res['Name']}"
            )
            results.append(res)

    results.sort(key=lambda r: (r["Institution"], r["Name"]))

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    output_report_path = "status/services_status.md"
    os.makedirs(os.path.dirname(output_report_path), exist_ok=True)

    with open(output_report_path, "w", encoding="utf-8") as f:
        f.write("# ArcGIS REST Service Status & Deep Crawl Report\n\n")
        f.write("This report is generated automatically by GitHub Actions once every week.\n\n")
        f.write(f"**Last checked:** {now_utc}\n\n")
        f.write("| Institution | Service | Status | HTTP | Response (ms) | Folders | Total Services | MapServer | FeatureServer | ImageServer | Other | Total Layers |\n")
        f.write("|---|---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")

        for r in results:
            f.write(
                f"| {r['Institution']} "
                f"| {r['Name']} "
                f"| {r['Status']} "
                f"| {r['HTTP']} "
                f"| {r['Response']} "
                f"| {r['Folders']} "
                f"| {r['TotalServices']} "
                f"| {r['MapServer']} "
                f"| {r['FeatureServer']} "
                f"| {r['ImageServer']} "
                f"| {r['OtherServer']} "
                f"| {r['TotalLayers']} |\n"
            )

    print("\nCheck and deep crawl finished successfully.")
    print(f"Unified status report written to {output_report_path}")


if __name__ == "__main__":
    main()
