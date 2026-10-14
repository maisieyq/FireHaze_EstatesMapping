"""CAMS global PM2.5 via Open-Meteo, with automatic coverage and persistent cache.

We store both the REQUESTED sample coordinates and the actual MODEL GRID CELL
coordinates returned by Open-Meteo. Visual smoothing does not add resolution.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import math
import time
import os
import numpy as np
import pandas as pd
import requests

from config import BASE, HAZE_CACHE_HOURS, HAZE_BATCH_SIZE, MAX_HAZE_LOCATIONS

OPEN_METEO_API_KEY = os.getenv('OPEN_METEO_API_KEY', '').strip()
API_URL = ('https://customer-api.open-meteo.com/v1/air-quality'
           if OPEN_METEO_API_KEY else 'https://air-quality-api.open-meteo.com/v1/air-quality')
CACHE_FILE = BASE / 'data' / 'cache' / 'haze_dynamic.csv'
FIELDS = ['requested_latitude', 'requested_longitude', 'latitude', 'longitude',
          'pm2_5', 'pm10', 'aod', 'pm25_24h_model', 'time', 'fetched_at_utc',
          'quality_flag', 'model', 'n_24h_hours']


def _read_cache():
    if not CACHE_FILE.exists():
        return pd.DataFrame(columns=FIELDS)
    try:
        frame = pd.read_csv(CACHE_FILE)
        if any(col not in frame for col in FIELDS):
            return pd.DataFrame(columns=FIELDS)
        return frame
    except (OSError, pd.errors.ParserError):
        return pd.DataFrame(columns=FIELDS)


def _save_cache(frame):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = CACHE_FILE.with_suffix('.tmp')
    frame.to_csv(temp, index=False)
    temp.replace(CACHE_FILE)

class OpenMeteoRateLimitError(RuntimeError):
    pass
def _query_batch(batch, session):
    params = {
        'latitude': ','.join(f'{lat:.5f}' for lat, lon in batch),
        'longitude': ','.join(f'{lon:.5f}' for lat, lon in batch),
        'current': 'pm2_5,pm10,aerosol_optical_depth',
        'hourly': 'pm2_5',
        'past_hours': 24,
        'forecast_hours': 1,
        'timezone': 'GMT',
        'domains': 'cams_global',
        'cell_selection': 'nearest',
    }
    if OPEN_METEO_API_KEY:
        params['apikey'] = OPEN_METEO_API_KEY
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(
                API_URL, 
                params=params, 
                timeout=75
            )

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")

                raise OpenMeteoRateLimitError(
                    f"Open-Meteo rate limit reached. "
                    f"Retry-After: {retry_after or 'not provided'}"
                )

            response.raise_for_status()

            data = response.json()
            if isinstance(data, dict):
                data = [data]
            if len(data) != len(batch):
                raise ValueError(f'Open-Meteo returned {len(data)} samples for {len(batch)} coordinates')
            return data
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt != 2:
                time.sleep(2**attempt)
    raise RuntimeError(f'Open-Meteo batch failed: {last_error}')


def _parse_result(requested, result, fetched_at):
    req_lat, req_lon = requested
    curr = result.get('current') or {}
    hourly = result.get('hourly') or {}
    pm = pd.to_numeric(curr.get('pm2_5'), errors='coerce')
    p10 = pd.to_numeric(curr.get('pm10'), errors='coerce')
    aod = pd.to_numeric(curr.get('aerosol_optical_depth'), errors='coerce')
    returned_lat = pd.to_numeric(result.get('latitude'), errors='coerce')
    returned_lon = pd.to_numeric(result.get('longitude'), errors='coerce')
    if not math.isfinite(float(returned_lat)) or not math.isfinite(float(returned_lon)):
        raise ValueError('Open-Meteo omitted actual model grid-cell coordinates')

    # 24h model average is additional context, NEVER labelled official API or AQI.
    times = pd.to_datetime(hourly.get('time', []), utc=True, errors='coerce')
    pm_series = pd.to_numeric(pd.Series(hourly.get('pm2_5', [])), errors='coerce')
    observed = pd.to_datetime(curr.get('time'), utc=True, errors='coerce')
    pm24 = float('nan')
    n_hours = 0
    if len(times) == len(pm_series) and pd.notna(observed):
        mask = (times <= observed) & (times > observed - pd.Timedelta(hours=24))
        values = pm_series[mask & pm_series.ge(0)]
        n_hours = len(values)
        if n_hours >= 12:
            pm24 = float(values.mean())

    flags = []
    if not np.isfinite(pm) or pm < 0:
        flags.append('missing_or_invalid_pm25')
        pm = float('nan')
    if np.isfinite(pm) and pm >= 250:
        flags.append('extreme_review')
    if np.isfinite(pm) and np.isfinite(p10) and pm > p10 * 1.05:
        flags.append('pm25_gt_pm10_review')

    return {
        'requested_latitude': round(req_lat, 5),
        'requested_longitude': round(req_lon, 5),
        'latitude': float(returned_lat),
        'longitude': float(returned_lon),
        'pm2_5': float(pm),
        'pm10': float(p10),
        'aod': float(aod),
        'pm25_24h_model': pm24,
        'n_24h_hours': n_hours,
        'time': curr.get('time'),
        'fetched_at_utc': fetched_at,
        'quality_flag': '|'.join(flags) or 'ok',
        'model': 'Open-Meteo / CAMS Global (0.4 degree)',
    }


def get_haze_data(lat, lon):
    with requests.Session() as session:
        result = _query_batch([(float(lat), float(lon))], session)[0]
    return result.get('current', {})


def get_estate_haze_locations(estates, gps_points):

    locations = set()

    # Choose one actual polygon reference location
    # per Company + SupplyBase, without estimating PM2.5
    geo = estates.to_crs("EPSG:4326").copy()

    geo["area_key"] = pd.to_numeric(
        geo["AreaHa"], errors="coerce"
    ).fillna(0)

    indexes = geo.groupby(
        ["Company", "SupplyBase"]
    )["area_key"].idxmax()

    selected = geo.loc[indexes]

    for point in selected.geometry.representative_point():

        locations.add((
            round(float(point.y), 5),
            round(float(point.x), 5)
        ))

    # Include existing GPS reference locations
    gps = gps_points.to_crs("EPSG:4326")

    for point in gps.geometry:

        if point is not None and not point.is_empty:

            locations.add((
                round(float(point.y), 5),
                round(float(point.x), 5)
            ))

    return sorted(locations)


def get_haze_grid(coverage_plan, force_refresh=False, session=None):
    desired = coverage_plan.haze_coordinates
    if len(desired) > MAX_HAZE_LOCATIONS:
        raise ValueError(f'Needed {len(desired)} sample locations exceeds safety cap '
                         f'{MAX_HAZE_LOCATIONS}. Raise MAX_HAZE_LOCATIONS only after reviewing API limits.')
    cached = _read_cache()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=HAZE_CACHE_HOURS)
    if not force_refresh and not cached.empty:
        fresh = cached[pd.to_datetime(cached.fetched_at_utc, utc=True, errors='coerce') >= cutoff].copy()
    else:
        fresh = pd.DataFrame(columns=FIELDS)
    fresh['key'] = list(zip(pd.to_numeric(fresh.requested_latitude, errors='coerce').round(5),
                            pd.to_numeric(fresh.requested_longitude, errors='coerce').round(5)))
    done = set(fresh['key'])
    outstanding = [point for point in desired if point not in done]
    print(f'CAMS Global: {len(desired)} points; {len(outstanding)} need refresh.')

    new_records = []
    owns_session = session is None
    if owns_session:
        session = requests.Session()
    failures = []
    try:
        for start in range(0, len(outstanding), HAZE_BATCH_SIZE):
            batch = outstanding[start:start+HAZE_BATCH_SIZE]
            try:
                results = _query_batch(batch, session)
                fetched_at = datetime.now(timezone.utc).isoformat()
                new_records.extend(_parse_result(point, result, fetched_at)
                                   
                                   for point, result in zip(batch, results))
                
                # Write successfully fetched batches immediately for resume after interruption.
                fresh_data = pd.DataFrame(new_records)
                merged = (fresh_data 
                          if cached.empty 
                          else pd.concat([cached, fresh_data], ignore_index=True))
                
                merged = merged.drop_duplicates(['requested_latitude', 'requested_longitude'], keep='last')
                _save_cache(merged[FIELDS])
                time.sleep(2)

            except OpenMeteoRateLimitError as exc:
                print(f"RATE LIMIT: {exc}")
                print(
                    "Stopping further haze requests. "
                    "Successfully downloaded batches remain cached."
                )
                break

            except (RuntimeError, ValueError) as exc:
                failures.extend(batch)
                print(f'WARNING: haze sample batch failed ({len(batch)} points): {exc}')
    
    finally:
        if owns_session:
            session.close()

    if outstanding:
        cached = _read_cache()
    else:
        cached = fresh.copy()
    cached['key'] = list(zip(pd.to_numeric(cached.requested_latitude, errors='coerce').round(5),
                             pd.to_numeric(cached.requested_longitude, errors='coerce').round(5)))
    valid_fresh = cached[pd.to_datetime(cached.fetched_at_utc, utc=True, errors='coerce') >= cutoff]
    selected = valid_fresh[valid_fresh['key'].isin(set(desired))].copy()
    selected = selected.drop_duplicates('key', keep='last')
    missing = set(desired)-set(selected['key'])
    selected = selected.drop(columns=['key']).reset_index(drop=True)
    # Do not silently re-use stale model samples or invent a clean PM2.5 value.
    # Fresh incomplete coverage is reported through metadata and exposure flags.
    selected.attrs['missing_sample_points'] = missing
    selected.attrs['requested_samples'] = len(desired)
    print(f'PM2.5 sample coverage: {len(selected)}/{len(desired)} fresh requested positions; '
          f'{len(missing)} unavailable')
    if selected.empty:
        raise RuntimeError('No fresh CAMS PM2.5 values available. Check Open-Meteo network/quota.')
    # Several requested points can map to the same real CAMS grid cell. Deduplicate
    # on ACTUAL coords so the plot doesn't falsely imply independent observations.
    before = len(selected)
    selected = selected.drop_duplicates(['latitude', 'longitude', 'time'], keep='last')
    print(f'Unique actual model grid locations: {len(selected)} (requests {before})')
    return selected

