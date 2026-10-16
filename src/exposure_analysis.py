
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

EARTH_KM = 6371.0088
FIRE_PRIMARY_RADIUS_KM = 5.0
FIRE_NEARBY_RADIUS_KM = 10.0
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

    required = [
        "requested_latitude",
        "requested_longitude",
        "latitude",
        "longitude",
        "pm2_5",
        "time"
    ]

    for col in required:
        if col not in data.columns:
            raise ValueError(f"Missing haze column: {col}")

    for col in required[:5]:
        data[col] = pd.to_numeric(
            data[col], errors="coerce"
        )

    data["time"] = pd.to_datetime(
        data["time"], utc=True, errors="coerce"
    )

    data = data.dropna(subset=required)

    data = data[
        data["requested_latitude"].between(-90, 90) &
        data["requested_longitude"].between(-180, 180) &
        data["latitude"].between(-90, 90) &
        data["longitude"].between(-180, 180) &
        (data["pm2_5"] >= 0)
    ].copy()

    if data.empty:
        return data

    # Accept samples from the latest model hour,
    # allowing up to 2 hours difference between batches.
    latest = data["time"].max()

    # Reject stale model data.
    now = pd.Timestamp.now(tz="UTC")

    if latest < now - pd.Timedelta(hours=6):
        return data.iloc[0:0].copy()

    data = data[
        (data["time"] >= latest - pd.Timedelta(hours=2)) &
        (data["time"] <= now + pd.Timedelta(hours=1))
    ].copy()

    # Preserve requested Estate GPS references.
    data = data.sort_values("time").drop_duplicates(
        ["requested_latitude", "requested_longitude"],
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

        # FIRE: 5 km primary screening; 10 km secondary alert.
        count_5km = None
        count_10km = None
        total_frp_5km = None
        total_frp_10km = None

        if fire_complete:
            indices_5km = (
                fire_tree.query_ball_point(
                    position, km_to_chord(FIRE_PRIMARY_RADIUS_KM)
                ) if fire_tree is not None else []
            )
            indices_10km = (
                fire_tree.query_ball_point(
                    position, km_to_chord(FIRE_NEARBY_RADIUS_KM)
                ) if fire_tree is not None else []
            )

            count_5km = len(indices_5km)
            count_10km = len(indices_10km)
            total_frp_5km = float(
                fire_data.iloc[indices_5km]["frp"].sum()
            ) if indices_5km else 0.0
            total_frp_10km = float(
                fire_data.iloc[indices_10km]["frp"].sum()
            ) if indices_10km else 0.0

        fire_rows.append({
            **common,
            "fires_inside": None,
            "fires_within_5km": count_5km,
            "fires_within_10km": count_10km,
            "total_frp_5km": total_frp_5km,
            "total_frp_10km": total_frp_10km,
            "fire_coverage_status": (
                "complete" if fire_complete
                else "incomplete"
            )
        })

        
        # HAZE: modelled PM2.5 requested at Estate GPS.
        pm = None
        distance_km = None
        sample_time = None

        if not haze_data.empty:
            matches = haze_data[
                np.isclose(
                    haze_data["requested_latitude"],
                    lat,
                    atol=0.00002,
                    rtol=0
                ) &
                np.isclose(
                    haze_data["requested_longitude"],
                    lon,
                    atol=0.00002,
                    rtol=0
                )
            ]

            if not matches.empty:
                sample = matches.sort_values(
                    "time"
                ).iloc[-1]

                pm = float(sample["pm2_5"])
                sample_time = sample["time"]

                # Distance to actual model grid centre.
                grid_position = xyz(
                    [sample["latitude"]],
                    [sample["longitude"]]
                )[0]

                chord_dist = np.linalg.norm(
                    position - grid_position
                )

                distance_km = (
                    2 * EARTH_KM *
                    np.arcsin(
                        np.clip(chord_dist / 2, 0, 1)
                    )
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
                "available" if pm is not None
                else "unavailable"
            ),
            "haze_time": (
                sample_time.isoformat()
                if sample_time is not None else None
            ),
            "source": "Open-Meteo / CAMS Global"
        })


    fire_ranking = pd.DataFrame(fire_rows)

    fire_ranking = fire_ranking.sort_values(
        ["fires_within_5km", "total_frp_5km", "fires_within_10km"],
        ascending=[False, False, False],
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
