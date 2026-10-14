import requests
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone

API_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
CACHE_FILE = Path(__file__).resolve().parent / "data" / "cache" / "haze_grid.csv"

def get_haze_data(lat, lon):

    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "pm2_5,pm10,aerosol_optical_depth",
        "domains": "cams_global"
    }

    response = requests.get(
        API_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    return data["current"]


if __name__ == "__main__":

    haze = get_haze_data(
        lat=3.139,
        lon=101.687
    )

    print(haze)



def get_haze_grid(force_refresh=False):

    # 1. Use cached data for up to 3 hours
    if CACHE_FILE.exists() and not force_refresh:
        modified = datetime.fromtimestamp(
            CACHE_FILE.stat().st_mtime,
            tz=timezone.utc
        )

        age = datetime.now(timezone.utc) - modified

        if age < timedelta(hours=3):
            print("Loading haze data from cache...")
            return pd.read_csv(CACHE_FILE)

    print("Fetching fresh haze data...")

    latitudes = np.arange(-10, 9, 2)
    longitudes = np.arange(95, 126, 2)

    coordinates = [
        (float(lat), float(lon))
        for lat in latitudes
        for lon in longitudes
    ]

    records = []
    batch_size = 20

    # 2. Download multiple locations per request
    for start in range(0, len(coordinates), batch_size):

        batch = coordinates[start:start + batch_size]

        params = {
            "latitude": ",".join(str(x[0]) for x in batch),
            "longitude": ",".join(str(x[1]) for x in batch),
            "current": "pm2_5,pm10,aerosol_optical_depth",
            "domains": "cams_global"
        }

        response = requests.get(
            API_URL,
            params=params,
            timeout=60
        )

        response.raise_for_status()

        results = response.json()

        if isinstance(results, dict):
            results = [results]

        if len(results) != len(batch):
            raise ValueError("Batch response count mismatch")

        for (lat, lon), result in zip(batch, results):

            current = result.get("current", {})

            records.append({
                "latitude": lat,
                "longitude": lon,
                "pm2_5": current.get("pm2_5"),
                "pm10": current.get("pm10"),
                "aod": current.get("aerosol_optical_depth"),
                "time": current.get("time")
            })

        print(
            f"Fetched {len(records)}/{len(coordinates)} locations"
        )

    haze_df = pd.DataFrame(records)

    # 3. Save to cache
    CACHE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    haze_df.to_csv(CACHE_FILE, index=False)

    print("Haze data saved to cache")
    print("Total haze points:", len(haze_df))

    return haze_df