
from pathlib import Path
from html import escape
from shutil import copy2

from config import OUTPUT


DASHBOARD_DIR = Path(__file__).resolve().parent


def make_rows(df, ranking_type):
    """Convert ranking DataFrame into HTML rows."""

    if ranking_type == "fire":
        df = df.sort_values(
            ["fires_inside", "fires_within_10km", "total_frp_10km"],
            ascending=False
        )
    else:
        df = df.sort_values(
            "pm2_5",
            ascending=False,
            na_position="last"
        )

    rows = []

    for rank, (_, row) in enumerate(df.iterrows(), start=1):

        company = escape(str(row["Company"]))
        estate = escape(str(row["SupplyBase"]))

        if ranking_type == "fire":
            metric = (
                f"{int(row['fires_within_10km'])} hotspots"
            )
            details = (
                f"Inside: {int(row['fires_inside'])} | "
                f"FRP: {float(row['total_frp_10km']):.1f} MW"
            )
        else:
            pm25 = row["pm2_5"]
            metric = (
                f"{float(pm25):.1f} µg/m³"
                if not __import__("pandas").isna(pm25)
                else "N/A"
            )
            details = "Modelled PM2.5 · regional screening"

        rows.append(f"""
        <div class="rank-card">
            <span class="rank-number">#{rank}</span>
            <div class="rank-info">
                <strong>{estate}</strong>
                <span>{company}</span>
                <small>{escape(details)}</small>
            </div>
            <div class="rank-value">{metric}</div>
        </div>
        """)

    return "\n".join(rows)


def build_dashboard(fire_ranking, haze_ranking):

    # Create dashboard output directory
    dest = OUTPUT.parent / "dashboard"
    dest.mkdir(parents=True, exist_ok=True)

    # Copy CSS and JavaScript
    copy2(DASHBOARD_DIR / "style.css", dest / "style.css")
    copy2(DASHBOARD_DIR / "dashboard.js", dest / "dashboard.js")

    fire_rows = make_rows(fire_ranking, "fire")
    haze_rows = make_rows(haze_ranking, "haze")

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">
    <title>Palm Oil Fire & Haze Dashboard</title>
    <link rel="stylesheet" href="style.css">
</head>

<body>

    <header class="dashboard-header">
        <div>
            <h1>Palm Oil Fire & Haze Monitor</h1>
            <p>Estate Exposure Dashboard</p>
        </div>
        <span class="status">Satellite + Model Data</span>
    </header>

    <main class="dashboard-layout">

        <section class="map-panel">
            <iframe
                src="../{escape(OUTPUT.name, quote=True)}"
                title="Interactive Estate Fire and Haze Map">
            </iframe>
        </section>

        <aside class="analysis-panel">

            <div class="panel-heading">
                <h2>Exposure Ranking</h2>
                <p>Company & Supply Base</p>
            </div>

            <div class="tab-buttons">
                <button id="fire-btn"
                        class="tab active"
                        onclick="switchTab('fire')">
                    Fire
                </button>

                <button id="haze-btn"
                        class="tab"
                        onclick="switchTab('haze')">
                    Haze
                </button>
            </div>

            <div id="fire-ranking" class="ranking-content">
                <h3>Fire Exposure Ranking</h3>
                <p class="description">
                    Ranked by detections inside polygons,
                    then within 10 km, then total nearby FRP.
                </p>
                {fire_rows}
            </div>

            <div id="haze-ranking"
                 class="ranking-content hidden">
                <h3>Haze Exposure Ranking</h3>
                <p class="description">
                    Ranked by modelled PM2.5 concentration.
                </p>
                {haze_rows}
            </div>

            <div class="method-note">
                Polygon-based ranking only. GPS-only companies
                require separate screening. Nearby fires do not
                establish responsibility for the fires.
            </div>

        </aside>

    </main>

    <script src="dashboard.js"></script>
</body>
</html>
"""

    index_path = dest / "index.html"
    index_path.write_text(html, encoding="utf-8")

    print("Dashboard saved:", index_path)

    return index_path
