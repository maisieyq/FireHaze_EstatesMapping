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
RATE_LIMIT_FILE = BASE / 'data' / 'cache' / 'openmeteo_cooldown.txt'

class OpenMeteoRateLimitError(RuntimeError):
    pass

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
    for attempt in range(30):
        try:
            response = session.get(API_URL, params=params, timeout=75)
            if response.status_code == 429:
                retry_after = response.headers.get('Retry-After')
                raise OpenMeteoRateLimitError(f'HTTP 429; Retry-After={retry_after or "not provided"}')
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                data = [data]
            if len(data) != len(batch):
                raise ValueError(f'Open-Meteo returned {len(data)} samples for {len(batch)} coordinates')
            return data
        except OpenMeteoRateLimitError:
            raise
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


def get_haze_grid(coverage_plan, force_refresh=False, session=None):
    """Request real CAMS model samples with 12-hour cache and resumable batches.

    Never substitutes missing points with nearby values. Returns only fresh samples.
    Historic records remain in CACHE_FILE for the map to read as *stale* samples.
    """
    desired = (coverage_plan.haze_coordinates if hasattr(coverage_plan, 'haze_coordinates')
               else list(coverage_plan))
    desired = list(dict.fromkeys(
        (round(float(lat), 5), round(float(lon), 5)) for lat, lon in desired
    ))
    if len(desired) > MAX_HAZE_LOCATIONS:
        raise ValueError(
            f'{len(desired)} sample positions exceed MAX_HAZE_LOCATIONS={MAX_HAZE_LOCATIONS}'
        )

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=HAZE_CACHE_HOURS)
    cache = _read_cache()
    if not cache.empty:
        cache = cache.copy()
        cache['_fetched'] = pd.to_datetime(cache['fetched_at_utc'], utc=True, errors='coerce')
        cache = cache.sort_values('_fetched').drop_duplicates(
            ['requested_latitude', 'requested_longitude'], keep='last'
        ).drop(columns=['_fetched'])

    # Only current-enough cached samples can be reused for a refresh.
    if force_refresh:
        fresh = pd.DataFrame(columns=FIELDS)
    else:
        timestamps = pd.to_datetime(cache['fetched_at_utc'], utc=True, errors='coerce')
        fresh = cache.loc[timestamps >= cutoff].copy()
        pm = pd.to_numeric(fresh['pm2_5'], errors='coerce')
        fresh = fresh.loc[np.isfinite(pm) & pm.ge(0)].copy()

    fresh_keys = set(zip(
        pd.to_numeric(fresh['requested_latitude'], errors='coerce').round(5),
        pd.to_numeric(fresh['requested_longitude'], errors='coerce').round(5)
    ))
    outstanding = [point for point in desired if point not in fresh_keys]
    print(f'CAMS Global: {len(desired)} locations; {len(outstanding)} need refresh.')

    # Local cooldown avoids repeated 429 storms. It does NOT guarantee that the
    # server's hourly / daily quota resets after the cooldown.
    cooldown = False
    if RATE_LIMIT_FILE.exists():
        try:
            retry_at = datetime.fromisoformat(RATE_LIMIT_FILE.read_text().strip())
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            cooldown = now < retry_at
        except (ValueError, OSError):
            pass
    if cooldown:
        print('Open-Meteo cooldown active; no new API calls will be made.')

    owns_session = session is None
    if owns_session:
        session = requests.Session()
    attempted = 0
    rate_limited = cooldown
    failed_batches = 0

    try:
        if not cooldown:
            for start in range(0, len(outstanding), HAZE_BATCH_SIZE):
                batch = outstanding[start:start + HAZE_BATCH_SIZE]
                try:
                    responses = _query_batch(batch, session)
                    fetched_at = datetime.now(timezone.utc).isoformat()
                    records = [
                        _parse_result(pt, resp, fetched_at)
                        for pt, resp in zip(batch, responses)
                    ]
                    updates = pd.DataFrame(records, columns=FIELDS)
                    # Save each successful batch: interrupted refreshes can resume.
                    cache = (updates if cache.empty else
                             pd.concat([cache, updates], ignore_index=True))
                    cache = cache.drop_duplicates(
                        ['requested_latitude', 'requested_longitude'], keep='last'
                    )
                    _save_cache(cache[FIELDS])
                    attempted += len(batch)
                    print(f'CAMS saved: {attempted}/{len(outstanding)} requested points')
                    # Deliberately throttle multi-coordinate requests.
                    # You may need longer if your Open-Meteo quota is exhausted.
                    if owns_session and start + len(batch) < len(outstanding):
                        time.sleep(2.0)
                except OpenMeteoRateLimitError as exc:
                    rate_limited = True
                    RATE_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
                    RATE_LIMIT_FILE.write_text(
                        (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
                    )
                    print(f'WARNING: {exc}; stopped remaining batches. Cache preserved.')
                    break
                except (RuntimeError, ValueError) as exc:
                    failed_batches += 1
                    print(f'WARNING: CAMS batch failed ({len(batch)} points): {exc}')
    finally:
        if owns_session:
            session.close()

    # Reload all successful batches, then keep only fresh *requested* records.
    cache = _read_cache()
    timestamps = pd.to_datetime(cache['fetched_at_utc'], utc=True, errors='coerce')
    recent = cache.loc[timestamps >= cutoff].copy()
    pm = pd.to_numeric(recent['pm2_5'], errors='coerce')
    recent = recent.loc[np.isfinite(pm) & pm.ge(0)].copy()
    recent['_key'] = list(zip(
        pd.to_numeric(recent['requested_latitude'], errors='coerce').round(5),
        pd.to_numeric(recent['requested_longitude'], errors='coerce').round(5)
    ))
    recent = recent[recent['_key'].isin(set(desired))]
    recent = recent.drop_duplicates('_key', keep='last')
    missing = set(desired) - set(recent['_key'])
    recent = recent.drop(columns=['_key'])

    # Multiple requests can resolve to one native CAMS grid centre.
    before = len(recent)
    recent = recent.drop_duplicates(['latitude', 'longitude', 'time'], keep='last')
    recent = recent.reset_index(drop=True)
    recent.attrs['requested_samples'] = len(desired)
    recent.attrs['fresh_requested_samples'] = before
    recent.attrs['missing_sample_points'] = missing
    recent.attrs['fetch_status'] = (
        'complete' if not missing else 'rate_limited' if rate_limited else 'partial'
    )
    recent.attrs['failed_batches'] = failed_batches
    print(f'CAMS: {before}/{len(desired)} requested positions fresh; '
          f'{len(recent)} distinct model cells; {len(missing)} unavailable.')
    return recent
