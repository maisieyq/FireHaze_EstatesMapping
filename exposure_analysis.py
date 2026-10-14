"""Estate-based exposure screening; missing data is never treated as zero.

Fire proximity != source attribution. PM2.5 values are CAMS regional model
estimates at ~45 km native grid resolution, not estate-site measurements.
"""
import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.spatial import cKDTree

from config import GPKG, OUTPUT
from coverage import fire_tiles_for_bounds

MAX_SAMPLE_DISTANCE_KM = 65.0  # screening threshold, not a model resolution claim


def _owned_polygons():
    gdf = gpd.read_file(GPKG, layer='estate_boundaries')
    gdf = gdf[gdf['Eligible_Own_Estate'].eq(True)].copy()
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    gdf['SupplyBase'] = gdf['SupplyBase'].fillna('Unknown').astype(str)
    return gdf


def _save(frame, name):
    out = OUTPUT.parent / name
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out, index=False)
    print('Saved:', out)


def calculate_fire_exposure(fires):
    original = _owned_polygons()
    completed = set(fires.attrs.get('complete_tiles', []))
    requested = set(fires.attrs.get('requested_tiles', []))
    geo = original.to_crs('EPSG:4326')
    coverage = {}
    for row in geo.itertuples():
        coverage.setdefault((row.Company, row.SupplyBase), set()).update(
            fire_tiles_for_bounds(row.geometry.bounds))

    # Avoid dissolving 5,000+ polygons (slow, may require GB of RAM).
    # Match each fire to component polygons, then deduplicate within Supply Base.
    keys=['Company','SupplyBase']
    result = original[keys].drop_duplicates().reset_index(drop=True)
    result['fires_inside'] = 0
    result['fires_within_10km'] = 0
    result['total_frp_10km'] = 0.0
    frame = fires.copy()
    for field in ['latitude','longitude']:
        if field not in frame:frame[field]=pd.Series(dtype=float)
        frame[field]=pd.to_numeric(frame[field],errors='coerce')
    frame=frame.dropna(subset=['latitude','longitude']).reset_index(drop=True)
    if 'frp' not in frame:frame['frp']=0.0
    frame['frp']=pd.to_numeric(frame.frp,errors='coerce').fillna(0)

    if len(frame):
        frame['fire_id']=frame.index
        fires_m=gpd.GeoDataFrame(frame, geometry=gpd.points_from_xy(frame.longitude,frame.latitude),
                                 crs='EPSG:4326').to_crs('EPSG:3395')
        orig_m=original[keys+['geometry']].to_crs('EPSG:3395')
        inside=gpd.sjoin(fires_m,orig_m,how='inner',predicate='intersects')
        inside=inside.drop_duplicates(['fire_id']+keys)
        inside_counts=inside.groupby(keys).size().rename('fires_inside')

        # EPSG:3395 is a regional screening approximation near the equator.
        buffer_m=orig_m.copy()
        buffer_m.geometry=buffer_m.geometry.buffer(10000)
        close=gpd.sjoin(fires_m,buffer_m,how='inner',predicate='intersects')
        close=close.drop_duplicates(['fire_id']+keys)
        nearby=close.groupby(keys).agg(fires_within_10km=('fire_id','size'),
                                       total_frp_10km=('frp','sum'))
        result=result.set_index(keys)
        result['fires_inside']=inside_counts.reindex(result.index).fillna(0).astype(int)
        result['fires_within_10km']=nearby['fires_within_10km'].reindex(result.index).fillna(0).astype(int)
        result['total_frp_10km']=nearby['total_frp_10km'].reindex(result.index).fillna(0.)
        result=result.reset_index()

    result['fire_coverage_status']=[
        'complete' if coverage.get((r.Company,r.SupplyBase),set()).issubset(completed)
            and coverage.get((r.Company,r.SupplyBase),set()).issubset(requested)
        else 'incomplete_unknown'
        for r in result.itertuples()
    ]
    missing=result.fire_coverage_status.ne('complete')
    result.loc[missing,['fires_inside','fires_within_10km','total_frp_10km']]=np.nan
    result=result.sort_values(['fire_coverage_status','fires_inside','fires_within_10km'],
                              ascending=[True,False,False])
    _save(result,'fire_exposure_ranking.csv')
    return result


def _xyz(lat_deg, lon_deg):
    lat = np.radians(np.asarray(lat_deg, dtype=float))
    lon = np.radians(np.asarray(lon_deg, dtype=float))
    return np.column_stack([np.cos(lat)*np.cos(lon),
                            np.cos(lat)*np.sin(lon), np.sin(lat)])


def calculate_haze_exposure(haze):
    original = _owned_polygons()
    geographic = original.to_crs('EPSG:4326')
    # Sample every source polygon rather than an arbitrary representative of a
    # very large dissolved SupplyBase, then compute approximate area-weighted
    # regional exposure. This is not a within-polygon physical PM2.5 reading.
    projected = original.to_crs('EPSG:3395')
    rep = projected.representative_point().to_crs('EPSG:4326')
    weights = pd.to_numeric(original.AreaHa, errors='coerce').fillna(0).to_numpy()
    fallback = projected.geometry.area.to_numpy()/10000.
    weights = np.where(weights > 0, weights, np.maximum(fallback, 0.001))

    values = haze.copy()
    for key in ['latitude','longitude','pm2_5']:
        values[key] = pd.to_numeric(values[key], errors='coerce')
    values = values.dropna(subset=['latitude','longitude','pm2_5'])
    values = values[values.pm2_5 >= 0].drop_duplicates(['latitude','longitude','time'])
    if values.empty:
        raise ValueError('No usable fresh PM2.5 model samples')

    tree = cKDTree(_xyz(values.latitude.values, values.longitude.values))
    chord, idx = tree.query(_xyz(rep.y.values, rep.x.values), k=1)
    dist_km = 2*6371.0088*np.arcsin(np.clip(chord/2, 0, 1))
    near = values.iloc[idx].reset_index(drop=True)
    sample_valid = dist_km <= MAX_SAMPLE_DISTANCE_KM

    records = pd.DataFrame({
        'Company': original.Company.values,
        'SupplyBase': original.SupplyBase.values,
        'area_weight': weights,
        'pm2_5': np.where(sample_valid, near.pm2_5.to_numpy(), np.nan),
        'pm25_24h_model': np.where(sample_valid,
            pd.to_numeric(near.get('pm25_24h_model'), errors='coerce').to_numpy(), np.nan),
        'distance_to_sample_km': dist_km,
        'quality_flag': np.where(sample_valid, near.quality_flag.fillna('unknown').values, 'too_far'),
        'haze_time': near.time.values,
    })

    grouped = []
    for (company, supply), group in records.groupby(['Company', 'SupplyBase']):
        valid = group.pm2_5.notna()
        cover = float(group.loc[valid, 'area_weight'].sum() / group.area_weight.sum())
        status = 'complete' if cover >= 0.999 else 'partial' if cover >= 0.90 else 'unavailable'
        if (group.loc[valid, 'quality_flag'].astype(str).str.contains('review')).any():
            if status != 'unavailable':
                status = 'review_required'
        # Threshold 90% is for regional screening only; report missing share.
        if cover >= 0.90:
            pm = float(np.average(group.loc[valid, 'pm2_5'], weights=group.loc[valid, 'area_weight']))
            ave24 = group.loc[valid & group.pm25_24h_model.notna()]
            pm24 = float(np.average(ave24.pm25_24h_model, weights=ave24.area_weight)) if not ave24.empty else np.nan
        else:
            pm = np.nan
            pm24 = np.nan
        times = group.loc[valid, 'haze_time'].dropna().unique()
        grouped.append({
            'Company': company, 'SupplyBase': supply,
            'pm2_5': pm, 'pm25_24h_model': pm24,
            'coverage_pct': round(cover*100, 1),
            'haze_coverage_status': status,
            'distance_to_sample_km': round(float(np.average(group.loc[valid, 'distance_to_sample_km'],
                    weights=group.loc[valid,'area_weight'])), 1) if valid.any() else np.nan,
            'polygon_features': len(group),
            'haze_time': times[0] if len(times)==1 else 'MIXED_TIMES' if len(times)>1 else '',
            'quality_flag': '|'.join(sorted(set(group.loc[valid,'quality_flag'].astype(str)))) if valid.any() else 'unavailable',
            'source': 'Open-Meteo CAMS Global model; ~45 km native resolution',
        })
    out = pd.DataFrame(grouped).sort_values('pm2_5', ascending=False, na_position='last')
    _save(out, 'haze_exposure_ranking.csv')
    return out
