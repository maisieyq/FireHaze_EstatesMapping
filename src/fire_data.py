"""NASA FIRMS detections fetched by tiled coverage around plantations.

The FIRMS API requires west,south,east,north and a 1-5-day window. Successful
empty tiles are treated as zero detections; failed tiles are flagged UNKNOWN.
"""
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import os
from pathlib import Path
import time

import pandas as pd
import requests

from config import MAP_KEY, BASE, FIRE_DAYS, FIRE_CACHE_HOURS
from coverage import tile_bbox, tile_id

CACHE_DIR = BASE / 'data' / 'cache' / 'fires_tiles'
SENSORS = ('VIIRS_NOAA20_NRT', 'VIIRS_NOAA21_NRT')
FIRE_COLUMNS = ['latitude', 'longitude', 'frp', 'acq_date', 'acq_time', 'sensor']


def _fetch_tile(session, sensor, tile, map_key):
    bounds = tile_bbox(tile)
    extent = ','.join(f'{val:g}' for val in bounds)
    url = ('https://firms.modaps.eosdis.nasa.gov/api/area/csv/'
           f'{map_key}/{sensor}/{extent}/{FIRE_DAYS}')
    for attempt in range(3):
        try:
            response = session.get(url, timeout=90)
            response.raise_for_status()
            content = response.text.strip()
            # Never include full URL or key in error output.
            if not content.lower().startswith('latitude,'):
                raise ValueError('Unexpected FIRMS CSV header or error response')
            frame = pd.read_csv(StringIO(content))
            frame['sensor'] = sensor
            return frame
        except (requests.RequestException, ValueError) as exc:
            if attempt == 2:
                raise RuntimeError(f'FIRMS request failed for {sensor} tile {tile_id(tile)} '
                                   f'({type(exc).__name__})') from None
            time.sleep(2**attempt)


def _tile_path(sensor, tile):
    return CACHE_DIR / f'{sensor}_{tile_id(tile)}.json'


def _read_cached(sensor, tile):
    path = _tile_path(sensor, tile)
    if not path.exists():
        return None
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
        fetched = datetime.fromisoformat(saved['fetched_at_utc'])
        if datetime.now(timezone.utc) - fetched > timedelta(hours=FIRE_CACHE_HOURS):
            return None
        if saved.get('sensor') != sensor or int(saved.get('days', -1)) != FIRE_DAYS:
            return None
        return pd.DataFrame(saved['records'])
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _save_cached(sensor, tile, frame):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _tile_path(sensor, tile)
    temp = p.with_suffix('.tmp')
    data = {
        'sensor': sensor, 'days': FIRE_DAYS,
        'tile': list(tile),
        'fetched_at_utc': datetime.now(timezone.utc).isoformat(),
        'records': frame.where(frame.notna(), None).to_dict('records'),
    }
    temp.write_text(json.dumps(data, default=str), encoding='utf-8')
    temp.replace(p)


def get_all_fires(coverage_plan, force_refresh=False, session=None, map_key=None):
    key = map_key or MAP_KEY
    if not key:
        raise RuntimeError('NASA_MAP_KEY missing. Set NASA_MAP_KEY in your local .env '
                           'to download fire detections (not bundled with this code).')
    owns_session = session is None
    if owns_session:
        session = requests.Session()
    frames = []
    ok = set()
    failed = set()
    try:
        for tile in coverage_plan.fire_tiles:
            tile_complete = True
            for sensor in SENSORS:
                frame = None if force_refresh else _read_cached(sensor, tile)
                if frame is None:
                    try:
                        frame = _fetch_tile(session, sensor, tile, key)
                        _save_cached(sensor, tile, frame)
                    except RuntimeError as exc:
                        tile_complete = False
                        print(f'WARNING: {exc} -- observations UNKNOWN for this tile')
                        continue
                if not frame.empty:
                    frames.append(frame)
            (ok if tile_complete else failed).add(tuple(tile))
    finally:
        if owns_session:
            session.close()

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FIRE_COLUMNS)
    if not df.empty:
        df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
        df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
        df = df.dropna(subset=['latitude','longitude'])
        dedup_keys = [c for c in ['sensor','latitude','longitude','acq_date','acq_time'] if c in df]
        df = df.drop_duplicates(dedup_keys).reset_index(drop=True)
    df.attrs['complete_tiles'] = ok
    df.attrs['failed_tiles'] = failed
    df.attrs['requested_tiles'] = set(map(tuple, coverage_plan.fire_tiles))
    print(f'NASA FIRMS coverage: {len(ok)}/{len(coverage_plan.fire_tiles)} region tiles complete; '
          f'{len(failed)} incomplete, {len(df)} detections')
    return df
