
from pathlib import Path
from html import escape
import re


def get_embedded_dashboard(index_path, map_path):

    index_path = Path(index_path)
    map_path = Path(map_path)

    # Read dashboard HTML
    html = index_path.read_text(encoding="utf-8")

    # Read CSS and JavaScript
    css = (index_path.parent / "style.css").read_text(
        encoding="utf-8"
    )

    js = (index_path.parent / "dashboard.js").read_text(
        encoding="utf-8"
    )

    # Read Folium map HTML
    map_html = map_path.read_text(encoding="utf-8")

    # Embed CSS directly
    html, css_count = re.subn(
        r'<link\s+rel="stylesheet"\s+href="style\.css"\s*/?>',
        lambda _: f"<style>{css}</style>",
        html,
        count=1
    )

    # Embed JavaScript directly
    html, js_count = re.subn(
        r'<script\s+src="dashboard\.js"\s*>\s*</script>',
        lambda _: f"<script>{js}</script>",
        html,
        count=1
    )

    # Embed Folium inside iframe using srcdoc
    iframe_pattern = r'<iframe\b[^>]*>.*?</iframe>'

    map_iframe = (
        '<iframe '
        'title="Interactive Estate Map" '
        f'srcdoc="{escape(map_html, quote=True)}" '
        'loading="eager">'
        '</iframe>'
    )

    html, iframe_count = re.subn(
        iframe_pattern,
        lambda _: map_iframe,
        html,
        count=1,
        flags=re.DOTALL
    )

    if (css_count, js_count, iframe_count) != (1, 1, 1):
        raise ValueError(
            "Dashboard template does not match expected "
            "CSS, JS or iframe structure."
        )

    return html
