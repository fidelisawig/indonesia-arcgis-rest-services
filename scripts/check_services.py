#!/usr/bin/env python3

import pandas as pd
import requests
from datetime import datetime

TIMEOUT = 20

SUPPORTED_TYPES = {
    "MapServer",
    "FeatureServer",
    "ImageServer",
    "SceneServer",
    "VectorTileServer"
}


def get_json(url):
    """Return (status_code, json, elapsed_ms)."""
    r = requests.get(
        url.rstrip("/"),
        params={"f": "pjson"},
        timeout=TIMEOUT
    )

    return (
        r.status_code,
        r.json(),
        round(r.elapsed.total_seconds() * 1000)
    )


def crawl(endpoint):
    """
    Crawl an ArcGIS REST endpoint recursively.
    """

    summary = {
        "folders": 0,
        "services": 0,
        "layers": 0,
        "mapservers": 0,
        "featureservers": 0,
        "imageservers": 0,
        "sceneservers": 0,
        "vectortiles": 0,
    }

    visited = set()

    def walk(url):

        if url in visited:
            return

        visited.add(url)

        try:

            code, j, _ = get_json(url)

            if code != 200:
                return

            if "error" in j:
                return

            # Count folders
            folders = j.get("folders", [])
            summary["folders"] += len(folders)

            # Visit folders
            for folder in folders:

                walk(f"{url}/{folder}")

            # Count services
            for svc in j.get("services", []):

                summary["services"] += 1

                svc_url = (
                    f"{url}/"
                    f"{svc['name']}/"
                    f"{svc['type']}"
                )

                t = svc["type"]

                if t == "MapServer":
                    summary["mapservers"] += 1

                elif t == "FeatureServer":
                    summary["featureservers"] += 1

                elif t == "ImageServer":
                    summary["imageservers"] += 1

                elif t == "SceneServer":
                    summary["sceneservers"] += 1

                elif t == "VectorTileServer":
                    summary["vectortiles"] += 1

                if t in SUPPORTED_TYPES:

                    try:

                        _, sj, _ = get_json(svc_url)

                        summary["layers"] += len(
                            sj.get("layers", [])
                        )

                    except Exception:
                        pass

        except Exception:
            pass

    walk(endpoint.rstrip("/"))

    return summary


########################################################################

catalog = pd.read_csv("data/services.csv")

rows = []

for _, row in catalog.iterrows():

    endpoint = row["URL"].rstrip("/")

    status = "❌ Offline"
    http = "-"
    elapsed = "-"

    try:

        http, j, elapsed = get_json(endpoint)

        if http == 200 and "error" not in j:

            status = "✅ Online"

            info = crawl(endpoint)

        else:

            info = {
                k: "-"
                for k in [
                    "folders",
                    "services",
                    "layers",
                    "mapservers",
                    "featureservers",
                    "imageservers",
                    "sceneservers",
                    "vectortiles",
                ]
            }

    except Exception:

        info = {
            k: "-"
            for k in [
                "folders",
                "services",
                "layers",
                "mapservers",
                "featureservers",
                "imageservers",
                "sceneservers",
                "vectortiles",
            ]
        }

    rows.append([
        row["Institution"],
        row["Name"],
        status,
        http,
        elapsed,
        info["folders"],
        info["services"],
        info["layers"],
        info["mapservers"],
        info["featureservers"],
        info["imageservers"],
        info["sceneservers"],
        info["vectortiles"],
    ])

########################################################################

today = datetime.utcnow().strftime("%Y-%m-%d")

with open(
    "status/services_status.md",
    "w",
    encoding="utf8"
) as f:

    f.write("# ArcGIS REST Service Status\n\n")

    f.write(f"Last checked: **{today} UTC**\n\n")

    f.write(
"| Institution | Service | Status | HTTP | ms | Folders | Services | Layers | Map | Feature | Image | Scene | Vector |\n"
    )

    f.write(
"|-------------|---------|:------:|----:|---:|--------:|---------:|-------:|----:|--------:|------:|------:|-------:|\n"
    )

    for r in rows:

        f.write(
            f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} | {r[7]} | {r[8]} | {r[9]} | {r[10]} | {r[11]} | {r[12]} |\n"
        )

print("Finished.")