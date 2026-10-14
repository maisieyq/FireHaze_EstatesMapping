import pandas as pd
import requests
from io import StringIO

from config import MAP_KEY, AREA, FIRE_DAYS

def get_fire_data(sensor):

    url = (
        "https://firms.modaps.eosdis.nasa.gov"
        f"/api/area/csv/{MAP_KEY}/"
        f"{sensor}/{AREA}/{FIRE_DAYS}"
    )

    response = requests.get(url, timeout=90)
    response.raise_for_status()

    content = response.text.strip()

    if not content.startswith("latitude,"):
        raise ValueError(
            f"Unexpected NASA response: {content[:300]}"
        )

    df = pd.read_csv(StringIO(content))
    df["sensor"] = sensor

    print(f"{sensor}: {len(df)} detections")

    return df


def get_all_fires():

    sensors = [
        "VIIRS_NOAA20_NRT",
        "VIIRS_NOAA21_NRT"
    ]

    fire_data = [
        get_fire_data(sensor)
        for sensor in sensors
    ]

    return pd.concat(
        fire_data,
        ignore_index=True
    )