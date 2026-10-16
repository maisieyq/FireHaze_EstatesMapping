
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

EARTH_KM = 6371.0088
FIRE_RADIUS_KM = 10.0
HAZE_MAX_DISTANCE_KM =100.0


def xyz(lat, lon):
    lat = np.radians(np.asarray(lat, dtype=float))
    lon = np.radians(np.asarray(lon, dtype=float))

    return np.column_stack([
        np.cos(lat) * np.cos(lon),
        np.cos(lat) * np.sin(lon),
        np.sin(lat)
    ])


def km_to_chord(km):
    return 2 * np.sin(km / (2 * EARTH_KM))


def prepare_locations(points):
    return points.copy()


def prepare_fires(fires):
    data = fires.copy()

    for col in ["latitude", "longitude", "frp"]:
        if col not in data:
            data[col] = np.nan

        data[col] = pd.to_numeric(
            data[col], errors="coerce"
        )

    data = data.dropna(
        subset=["latitude", "longitude"]
    )

    data = data[
        data.latitude.between(-90, 90) &
        data.longitude.between(-180, 180)
    ]

    identity = [
        "sensor", "latitude", "longitude",
        "acq_date", "acq_time"
    ]

    if all(c in data.columns for c in identity):
        data = data.drop_duplicates(identity)

    return data.reset_index(drop=True)


def prepare_haze(haze):
    data = haze.copy()

    for col in ["latitude", "longitude", "pm2_5"]:
        if col not in data:
            data[col] = np.nan

        data[col] = pd.to_numeric(
            data[col], errors="coerce"
        )

    data = data.dropna(
        subset=["latitude", "longitude", "pm2_5"]
    )

    data = data[
        data.latitude.between(-90, 90) &
        data.longitude.between(-180, 180) &
        (data.pm2_5 >= 0)
    ].copy()

    if not data.empty and "time" in data.columns:
        data = data[
            data["time"] == data["time"].max()
        ].copy()

    data = data.drop_duplicates(
        ["latitude", "longitude"],
        keep="last"
    )

    return data.reset_index(drop=True)


def calculate_exposure(points, fires, haze):
    locations = prepare_locations(points)
    fire_data = prepare_fires(fires)
    haze_data = prepare_haze(haze)

    fire_tree = None
    haze_tree = None
    haze_vectors = None

    if not fire_data.empty:
        fire_tree = cKDTree(
            xyz(
                fire_data.latitude,
                fire_data.longitude
            )
        )

    if not haze_data.empty:
        haze_vectors = xyz(
            haze_data.latitude,
            haze_data.longitude
        )

        haze_tree = cKDTree(haze_vectors)

    # Missing NASA tiles mean fire count is unknown.
    fire_complete = not bool(
        fires.attrs.get("failed_tiles", [])
    )

    fire_rows = []
    haze_rows = []

    for estate in locations.itertuples(index=False):
        lat = float(estate.latitude)
        lon = float(estate.longitude)

        position = xyz([lat], [lon])[0]

        common = {
            "Company": estate.company,
            "SupplyBase": estate.estate_name,
            "latitude": lat,
            "longitude": lon,
            "point_source": getattr(
                estate, "coordinate_basis", ""
            )
        }

        # FIRE: satellite detections within 10 km.
        count = None
        total_frp = None

        if fire_complete:
            indices = (
                fire_tree.query_ball_point(
                    position,
                    km_to_chord(FIRE_RADIUS_KM)
                )
                if fire_tree is not None else []
            )

            count = len(indices)

            total_frp = float(
                fire_data.iloc[indices]["frp"].sum()
            ) if indices else 0.0

        fire_rows.append({
            **common,
            "fires_inside": None,
            "fires_within_10km": count,
            "total_frp_10km": total_frp,
            "fire_coverage_status": (
                "complete" if fire_complete
                else "incomplete"
            )
        })

        # HAZE: nearest valid model cell.
        pm = None
        distance_km = None

        if haze_tree is not None:
            chord_dist, index = haze_tree.query(position)

            distance_km = (
                2 * EARTH_KM *
                np.arcsin(
                    np.clip(chord_dist / 2, 0, 1)
                )
            )

            if distance_km <= HAZE_MAX_DISTANCE_KM:
                pm = float(
                    haze_data.iloc[int(index)]["pm2_5"]
                )

        haze_rows.append({
            **common,
            "pm2_5": pm,
            "coverage_pct": (
                100.0 if pm is not None else 0.0
            ),
            "distance_to_sample_km": (
                round(float(distance_km), 1)
                if distance_km is not None else None
            ),
            "haze_coverage_status": (
                "complete" if pm is not None
                else "unavailable"
            )
        })

    fire_ranking = pd.DataFrame(fire_rows)

    fire_ranking = fire_ranking.sort_values(
        ["fires_within_10km", "total_frp_10km"],
        ascending=[False, False],
        na_position="last"
    ).reset_index(drop=True)

    haze_ranking = pd.DataFrame(haze_rows)

    haze_ranking = haze_ranking.sort_values(
        "pm2_5",
        ascending=False,
        na_position="last"
    ).reset_index(drop=True)

    print("Fire Ranking:", len(fire_ranking))
    print("Haze Ranking:", len(haze_ranking))

    return fire_ranking, haze_ranking
