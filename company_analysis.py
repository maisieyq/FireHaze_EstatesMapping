"""Comparable company/estate rankings and cross-metric screening context.

No GPS-only company is silently treated as having an estate footprint.
Do not interpret NASA thermal anomalies as proof of fire causation.
"""
import numpy as np
import pandas as pd
import geopandas as gpd
from exposure_analysis import _owned_polygons


def _company_areas(source):
    geo = source.to_crs('EPSG:6933')
    weights = pd.to_numeric(source.get('AreaHa', pd.Series(index=source.index, dtype=float)), errors='coerce').fillna(0).to_numpy()
    derived = geo.geometry.area.to_numpy() / 10000
    weights = np.where(weights > 0, weights, np.maximum(derived, 0.001))
    table = source[['Company', 'SupplyBase']].copy()
    table['area_ha'] = weights
    return table.groupby(['Company', 'SupplyBase'], as_index=False).area_ha.sum()


def calculate_company_rankings(fire_by_base, haze_by_base, fires, gps_points=None, owned=None):
    """Build company results; fire records are deduplicated within each company."""
    source = owned.copy() if owned is not None else _owned_polygons()
    source['SupplyBase'] = source['SupplyBase'].fillna('Unknown').astype(str)
    areas = _company_areas(source)
    companies = sorted(set(source.Company.dropna().astype(str)) | (
        set(gps_points.Company.dropna().astype(str)) if gps_points is not None else set()))
    frp_source = fires.copy() if fires is not None else pd.DataFrame()
    nearby = pd.DataFrame(columns=['Company', 'fires_inside', 'fires_within_10km', 'total_frp_10km'])
    if not frp_source.empty:
        frame = frp_source.copy()
        for f in ['latitude','longitude','frp']:
            frame[f] = pd.to_numeric(frame.get(f), errors='coerce')
        frame = frame.dropna(subset=['latitude','longitude']).reset_index(drop=True)
        if not frame.empty:
            frame['fire_id'] = frame.index
            frame['frp'] = frame.frp.fillna(0)
            fire_geo = gpd.GeoDataFrame(frame, geometry=gpd.points_from_xy(frame.longitude,frame.latitude),crs='EPSG:4326').to_crs('EPSG:3395')
            area_geo = source[['Company','geometry']].to_crs('EPSG:3395')
            within = gpd.sjoin(fire_geo,area_geo,how='inner',predicate='intersects')
            within = within.drop_duplicates(['fire_id','Company'])
            counts = within.groupby('Company').size().rename('fires_inside')
            buffered = area_geo.copy()
            buffered.geometry = buffered.geometry.buffer(10000)
            ten = gpd.sjoin(fire_geo,buffered,how='inner',predicate='intersects')
            ten = ten.drop_duplicates(['fire_id','Company'])
            nearby = ten.groupby('Company').agg(fires_within_10km=('fire_id','size'),total_frp_10km=('frp','sum'))
            nearby['fires_inside'] = counts.reindex(nearby.index).fillna(0).astype(int)
            nearby = nearby.reset_index()
    frp_lookup = nearby.set_index('Company') if not nearby.empty else pd.DataFrame()
    rows=[]
    for company in companies:
        parts=areas[areas.Company == company]
        if parts.empty:
            rows.append({'Company':company,'supply_bases':0,'area_ha':np.nan,
                         'fire_coverage_status':'boundary_unavailable','fires_inside':np.nan,
                         'fires_within_10km':np.nan,'total_frp_10km':np.nan,'fires_per_1000ha':np.nan,
                         'pm2_5':np.nan,'pm25_24h_model':np.nan,'haze_coverage_status':'boundary_unavailable',
                         'coverage_pct':0.0})
            continue
        area=float(parts.area_ha.sum())
        fr=fire_by_base[fire_by_base.Company==company]
        fire_ok=(len(fr)==len(parts) and fr.fire_coverage_status.eq('complete').all())
        if fire_ok and company in frp_lookup.index:
            frow=frp_lookup.loc[company]
            inside=int(frow['fires_inside']); around=int(frow['fires_within_10km']); energy=float(frow['total_frp_10km'])
        elif fire_ok:
            inside=around=0;energy=0.
        else:
            inside=around=energy=np.nan
        hz=haze_by_base[haze_by_base.Company==company]
        weighted=parts.merge(hz,on=['Company','SupplyBase'],how='left')
        cov=pd.to_numeric(weighted.get('coverage_pct'),errors='coerce').fillna(0).clip(0,100)/100
        valid=(pd.to_numeric(weighted.get('pm2_5'),errors='coerce').notna())
        coverage=float((weighted.area_ha * cov).sum()/area) if area else 0.
        pm2=pd.to_numeric(weighted.get('pm2_5'), errors='coerce')
        hweight=weighted.area_ha * cov
        pm=np.average(pm2[valid],weights=hweight[valid]) if valid.any() and hweight[valid].sum()>0 and coverage>=0.9 else np.nan
        pm24=pd.to_numeric(weighted.get('pm25_24h_model'),errors='coerce')
        valid24=valid & pm24.notna()
        mean24=np.average(pm24[valid24],weights=hweight[valid24]) if valid24.any() and hweight[valid24].sum()>0 and coverage>=0.9 else np.nan
        status = 'complete' if coverage>=.999 else 'partial' if coverage>=.9 else 'unavailable'
        if status!='unavailable' and hz.haze_coverage_status.astype(str).str.contains('review_required').any():status='review_required'
        rows.append({'Company':company,'supply_bases':int(len(parts)),'area_ha':area,
                     'fire_coverage_status':'complete' if fire_ok else 'incomplete_unknown',
                     'fires_inside':inside,'fires_within_10km':around,'total_frp_10km':energy,
                     'fires_per_1000ha':around*1000/area if fire_ok and area>0 else np.nan,
                     'pm2_5':pm,'pm25_24h_model':mean24,
                     'haze_coverage_status':status,'coverage_pct':round(coverage*100,1)})
    return pd.DataFrame(rows)


def build_summary(fire_rank, haze_rank, company_rank):
    status = {}
    status['companies'] = len(company_rank)
    status['supply_bases'] = len(fire_rank)
    status['fire_available_bases'] = int(fire_rank.fire_coverage_status.eq('complete').sum())
    status['haze_available_bases'] = int(haze_rank.pm2_5.notna().sum())
    complete = company_rank[company_rank.fire_coverage_status.eq('complete')]
    status['fire_available_companies'] = len(complete)
    valid = company_rank[company_rank.pm2_5.notna()]
    status['haze_available_companies'] = len(valid)
    status['highest_haze_company'] = (valid.sort_values('pm2_5',ascending=False).iloc[0]['Company'] if len(valid) else None)
    positive = complete[pd.to_numeric(complete['fires_per_1000ha'], errors='coerce') > 0]
    status['most_fire_company'] = (positive.sort_values('fires_per_1000ha',ascending=False).iloc[0]['Company'] if len(positive) else None)
    return status
