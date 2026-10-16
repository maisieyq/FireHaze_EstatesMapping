
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from estate_data import load_estates
from coverage import plan_coverage
from exposure_analysis import calculate_exposure
from fire_data import get_all_fires
from haze_data import get_haze_grid
from haze_overlay import create_haze_overlay

DEST = ROOT / "web" / "data"


def save_json(filename, data):
    DEST.mkdir(parents=True, exist_ok=True)

    target = DEST / filename
    temp = DEST / (filename + ".tmp")

    temp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False
        ),
        encoding="utf-8"
    )

    os.replace(temp, target)


def records(df):
    return json.loads(
        df.to_json(
            orient="records",
            date_format="iso"
        )
    )


def export_locations(points, boundaries):
    features = []

    for row in points.to_dict("records"):
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [
                    float(row["longitude"]),
                    float(row["latitude"])
                ]
            },
            "properties": {
                "Company": row["company"],
                "SupplyBase": row["estate_name"],
                "Estate_Name": row["estate_name"],
                "coordinate_basis": row.get(
                    "coordinate_basis", ""
                ),
                "country": row.get("country", "")
            }
        })

    for feature in boundaries["features"]:
        props = feature.setdefault("properties", {})

        props["Company"] = props.get("company", "")
        props["SupplyBase"] = props.get(
            "estate_name", ""
        )

    save_json("points.geojson", {
        "type": "FeatureCollection",
        "features": features
    })

    save_json("estates.geojson", boundaries)


def update_data(force=False):
    DEST.mkdir(parents=True, exist_ok=True)

    print("1/6 Loading plantation data...")
    points, boundaries = load_estates()

    print("2/6 Planning coverage...")
    coverage = plan_coverage(points)

    print("3/6 Downloading Fire Data...")
    fires = get_all_fires(
        coverage,
        force_refresh=force
    )

    print("4/6 Downloading Haze Data...")
    haze = get_haze_grid(
        coverage,
        force_refresh=force
    )

    if fires.attrs.get("failed_tiles"):
        raise RuntimeError(
            "NASA Fire download incomplete"
        )

    if (
        haze.empty or
        haze.attrs.get("fetch_status") != "complete"
    ):
        raise RuntimeError(
            "Haze download incomplete"
        )

    print("5/6 Calculating Exposure Ranking...")
    fire_ranking, haze_ranking = calculate_exposure(
        points, fires, haze
    )

    print("6/6 Generating Continuous Haze Map...")
    create_haze_overlay(haze, DEST)

    export_locations(points, boundaries)

    save_json(
        "fires.json",
        records(fires)
    )

    save_json(
        "haze.json",
        records(haze)
    )

    save_json("rankings.json", {
        "fire": records(fire_ranking),
        "haze": records(haze_ranking)
    })

    now = datetime.now(timezone.utc).isoformat()

    fire_dates = (
        fires["acq_date"].dropna().astype(str)
        if "acq_date" in fires else []
    )

    haze_times = (
        haze["time"].dropna().astype(str)
        if "time" in haze else []
    )

    meta = {
        "companies": sorted(
            points["company"].unique().tolist()
        ),
        "fire_count": len(fires),
        "haze_samples": len(haze),
        "point_count": len(points),
        "polygon_count": len(boundaries["features"]),
        "fire_detection_date": (
            max(fire_dates) if len(fire_dates) else None
        ),
        "haze_model_time": (
            max(haze_times) if len(haze_times) else None
        ),
        "fire_saved_at": now,
        "updated_at": now,
        "analysis_method": "Point-based screening",
        "fire_radius_km": 10,
        "haze_max_sample_distance_km": 65
    }

    # Meta is written last to indicate completed output.
    save_json("meta.json", meta)

    print("Update completed:", now)

    return meta


if __name__ == "__main__":
    update_data(force=False)
