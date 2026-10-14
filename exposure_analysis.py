
import pandas as pd
import geopandas as gpd
import numpy as np

from config import GPKG, OUTPUT


def calculate_fire_exposure(fires):

    # Use original boundaries for analysis
    estates = gpd.read_file(
        GPKG,
        layer="estate_boundaries"
    )

    estates = estates[
        estates["Eligible_Own_Estate"].eq(True)
    ].copy()

    estates = estates[
        estates.geometry.notna()
        & ~estates.geometry.is_empty
    ].copy()

    # One analysis unit per Company + SupplyBase
    estates["SupplyBase"] = (
        estates["SupplyBase"]
        .fillna("Unknown")
        .astype(str)
    )

    estates = estates.dissolve(
        by=["Company", "SupplyBase"],
        as_index=False
    )

    # Fire points
    fire_gdf = gpd.GeoDataFrame(
        fires.copy(),
        geometry=gpd.points_from_xy(
            fires["longitude"],
            fires["latitude"]
        ),
        crs="EPSG:4326"
    )

    fire_gdf["frp"] = pd.to_numeric(
        fire_gdf["frp"],
        errors="coerce"
    ).fillna(0)

    # Approximate metric CRS for regional screening
    estates_m = estates.to_crs("EPSG:3857")
    fires_m = fire_gdf.to_crs("EPSG:3857")

    estates_m = estates_m.reset_index(drop=True)
    estates_m["unit_id"] = estates_m.index

    # 1. Fires inside plantation boundary
    inside = gpd.sjoin(
        fires_m,
        estates_m[["unit_id", "geometry"]],
        how="inner",
        predicate="intersects"
    )

    inside_count = (
        inside.groupby("unit_id")
        .size()
        .rename("fires_inside")
    )

    # 2. Fires within 10 km of boundary
    buffers = estates_m[
        ["unit_id", "geometry"]
    ].copy()

    buffers["geometry"] = (
        buffers.geometry.buffer(10000)
    )

    nearby = gpd.sjoin(
        fires_m,
        buffers,
        how="inner",
        predicate="intersects"
    )

    nearby_summary = nearby.groupby("unit_id").agg(
        fires_within_10km=("frp", "size"),
        total_frp_10km=("frp", "sum")
    )

    # Combine results
    result = estates_m[
        ["unit_id", "Company", "SupplyBase"]
    ].copy()

    result = result.join(
        inside_count,
        on="unit_id"
    )

    result = result.join(
        nearby_summary,
        on="unit_id"
    )

    result = result.fillna({
        "fires_inside": 0,
        "fires_within_10km": 0,
        "total_frp_10km": 0
    })

    result = result.sort_values(
        ["fires_inside", "fires_within_10km"],
        ascending=False
    )

    output_path = (
        OUTPUT.parent / "fire_exposure_ranking.csv"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    result.to_csv(output_path, index=False)

    print("\nTop 10 Fire Exposure Areas:")
    print(result.head(10).to_string(index=False))

    print("\nSaved:", output_path)

    return result


def calculate_haze_exposure(haze):

    estates = gpd.read_file(
        GPKG,
        layer="estate_boundaries"
    )

    estates = estates[
        estates["Eligible_Own_Estate"].eq(True)
    ].copy()

    estates["SupplyBase"] = (
        estates["SupplyBase"]
        .fillna("Unknown")
        .astype(str)
    )

    estates = estates.dissolve(
        by=["Company", "SupplyBase"],
        as_index=False
    )

    # Find representative location for each unit
    points = estates.to_crs("EPSG:3857")
    points["geometry"] = (
        points.geometry.representative_point()
    )
    points = points.to_crs("EPSG:4326")

    # Remove missing haze values
    haze = haze.dropna(
        subset=["latitude", "longitude", "pm2_5"]
    ).copy()

    if haze.empty:
        raise ValueError("No usable PM2.5 data")

    records = []

    haze_lat = np.radians(
        haze["latitude"].to_numpy(dtype=float)
    )
    haze_lon = np.radians(
        haze["longitude"].to_numpy(dtype=float)
    )

    for _, estate in points.iterrows():

        lat = np.radians(estate.geometry.y)
        lon = np.radians(estate.geometry.x)

        # Haversine distances, in kilometres
        dlat = haze_lat - lat
        dlon = haze_lon - lon

        a = (
            np.sin(dlat / 2) ** 2
            + np.cos(lat)
            * np.cos(haze_lat)
            * np.sin(dlon / 2) ** 2
        )

        distances = 6371.0 * 2 * np.arcsin(
            np.sqrt(np.clip(a, 0, 1))
        )

        nearest_pos = int(np.argmin(distances))
        nearest = haze.iloc[nearest_pos]

        records.append({
            "Company": estate["Company"],
            "SupplyBase": estate["SupplyBase"],
            "pm2_5": nearest["pm2_5"],
            "aod": nearest.get("aod"),
            "distance_to_sample_km": (
                distances[nearest_pos]
            ),
            "haze_time": nearest.get("time")
        })

    result = pd.DataFrame(records)

    result = result.sort_values(
        "pm2_5",
        ascending=False
    )

    output_path = (
        OUTPUT.parent / "haze_exposure_ranking.csv"
    )

    result.to_csv(output_path, index=False)

    print("\nTop 10 Regional Haze Exposure Areas:")
    print(result.head(10).to_string(index=False))

    print("\nSaved:", output_path)

    return result
