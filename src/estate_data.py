
from pathlib import Path
import json

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "source_data"


def load_estates():
    points_path = SOURCE / "estate_exposure_points.csv"
    boundary_path = SOURCE / "estate_boundaries.geojson"

    if not points_path.exists():
        raise FileNotFoundError(points_path)

    if not boundary_path.exists():
        raise FileNotFoundError(boundary_path)

    points = pd.read_csv(points_path)

    required = [
        "company",
        "estate_name",
        "latitude",
        "longitude"
    ]

    for field in required:
        if field not in points.columns:
            raise ValueError(f"Missing CSV field: {field}")

    points["latitude"] = pd.to_numeric(
        points["latitude"], errors="coerce"
    )

    points["longitude"] = pd.to_numeric(
        points["longitude"], errors="coerce"
    )

    points = points.dropna(subset=required).copy()

    points = points[
        points.latitude.between(-90, 90) &
        points.longitude.between(-180, 180)
    ].reset_index(drop=True)

    with open(boundary_path, encoding="utf-8") as f:
        boundaries = json.load(f)

    if boundaries.get("type") != "FeatureCollection":
        raise ValueError("Invalid estate boundaries GeoJSON")

    print("Estate reference points:", len(points))
    print("Boundary features:", len(boundaries["features"]))

    return points, boundaries
