from pathlib import Path
import os
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env')

# NASA key must exist at fire fetch time; do not bundle keys in shared archives.
MAP_KEY = os.getenv('NASA_MAP_KEY')
GPKG = BASE / 'data' / 'all_company_geometries.gpkg'
OUTPUT = BASE / 'output' / 'estate_fire_map.html'
FIRE_DAYS = 3
MAP_CENTER = [1.6, 109.8]  # fallback only; map auto-fits estate data
MAP_ZOOM = 5

# Tune these if service quota/plan requires more conservative requests.
HAZE_CACHE_HOURS = 3
FIRE_CACHE_HOURS = 3
HAZE_BATCH_SIZE = 25
MAX_HAZE_LOCATIONS = 2500

COLORS = {
    'United Plantations Berhad': '#2EF0C9',
    'Bumitama Agri': '#A5FFF3',
    'IOI Corporation': '#75E2FF',
    'SD Guthrie': '#AEFF9A',
    'Sarawak Plantation Berhad': '#C8FFE4',
    'Hap Seng Plantations': '#F4FBFF',
}
