
'use strict';

const root = 'data/';
let mode = 'fire';
let rankings = { fire: [], haze: [] };
let map, fireLayer, hazeLayer, estateLayer, pointLayer;

const companyLayers = new Map();
const $ = id => document.getElementById(id);

const fmt = (n, d = 0) =>
    Number.isFinite(Number(n))
        ? Number(n).toLocaleString(undefined, {
            maximumFractionDigits: d,
            minimumFractionDigits: d
        })
        : 'N/A';

const number = n =>
    n === null || n === undefined || n === '' ||
    !Number.isFinite(Number(n)) ? null : Number(n);

const esc = v =>
    String(v ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[c]));

const get = async f => {
    const r = await fetch(root + f);
    if (!r.ok) throw Error(f + ' HTTP ' + r.status);
    return r.json();
};

function companyColor(n) {
    const colors = {
        "United Plantations Berhad": "#2E8B57",
        "Bumitama Agri": "#E6A23C",
        "IOI Corporation": "#4285F4",
        "SD Guthrie": "#9B59B6",
        "Hap Seng Plantations": "#E76F51",
        "Sarawak Plantation": "#64748B"
    };

    return colors[n] || "#64748B";;
}

function setupMap() {
    map = L.map('map', {
        preferCanvas: true,
        zoomControl: true
    }).setView([1.7, 109.5], 5);

    L.tileLayer(
        'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        {
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 19
        }
    ).addTo(map);

    map.createPane('hazePane');
    map.getPane('hazePane').style.zIndex = '350';
    map.getPane('hazePane').style.pointerEvents = 'none';
    
    fireLayer = L.layerGroup().addTo(map);
    hazeLayer = L.layerGroup().addTo(map);
}

function updateLegend() {
    const showFire = $('fire-map').checked;
    const showHaze = $('haze-map').checked;
    const entries = [];

    if (showFire) {
        entries.push(
            '<div><span class="dot" style="background:#e36530"></span>NASA thermal detections</div>'
        );
    }

    if (showHaze) {
        entries.push(`
            <br>
            <div><strong>PM2.5 (µg/m³)</strong></div>
            <div>
                <span class="dot" style="background:#67b6cf"></span>
                Below 15
            </div>
            <div>
                <span class="dot" style="background:#91c9a4"></span>
                15–25
            </div>
            <div>
                <span class="dot" style="background:#eed27b"></span>
                25–35
            </div>
            <div>
                <span class="dot" style="background:#e99460"></span>
                35–55
            </div>
            <div>
                <span class="dot" style="background:#c95563"></span>
                55+
            </div>
        `);
    }

    $('map-legend').innerHTML = entries.length
        ? '<strong>Environmental overlays</strong>' + entries.join('')
        : '<strong>No environmental overlays selected</strong>';
}

function syncOverlay() {
    for (const [id, layer] of [
        ['fire-map', fireLayer],
        ['haze-map', hazeLayer]
    ]) {
        if ($(id).checked) {
            if (!map.hasLayer(layer)) map.addLayer(layer);
        } else if (map.hasLayer(layer)) {
            map.removeLayer(layer);
        }
    }

    updateLegend();
}

function syncCompanies() {
    const showBoundaries = $('boundaries').checked;
    const showPoints = $('references').checked;

    for (const [company, layers] of companyLayers) {
        const checked = layers.checkbox.checked;

        for (const [layer, enabled] of [
            [layers.boundaries, showBoundaries],
            [layers.points, showPoints]
        ]) {
            if (checked && enabled) {
                if (!map.hasLayer(layer)) map.addLayer(layer);
            } else if (map.hasLayer(layer)) {
                map.removeLayer(layer);
            }
        }
    }
}

function modeSet(next) {
    mode = next;

    $('fire-btn').classList.toggle('active', next === 'fire');
    $('haze-btn').classList.toggle('active', next === 'haze');

    $('rank-desc').textContent = next === 'fire'
        ? 'Supply bases: inside detections, then within 10 km, then FRP. Company view: sum across bases (descriptive, not deduplicated).'
        : 'Modelled PM2.5 (µg/m³). N/A means unavailable or inadequate coverage. Company view uses available base samples.';

    // Ranking switch does not change map overlays.
    renderRanks();
}

function aggregated(data, kind) {
    const group = new Map();

    for (const row of data) {
        const k = row.Company ?? 'Unknown';

        if (!group.has(k)) {
            group.set(k, {
                Company: k,
                SupplyBase: k,
                fireInside: 0,
                fireNearby: 0,
                frp: 0,
                fireValid: 0,
                pmWeight: 0,
                pmWeighted: 0,
                pmCount: 0,
                bases: 0
            });
        }

        const x = group.get(k);
        x.bases++;

        if (
            kind === 'fire' &&
            row.fire_coverage_status === 'complete' &&
            number(row.fires_within_10km) !== null
        ) {
            x.fireValid++;
            x.fireNearby += number(row.fires_within_10km) || 0;
            x.frp += number(row.total_frp_10km) || 0;
        }

        if (
            kind === 'haze' &&
            number(row.pm2_5) !== null &&
            number(row.coverage_pct) >= 90
        ) {
            const w = number(row.area_ha_sum) || 1;
            x.pmWeighted += Number(row.pm2_5) * w;
            x.pmWeight += w;
            x.pmCount++;
        }
    }

    return [...group.values()].map(x => ({
        Company: x.Company,
        SupplyBase: x.Company,
        bases: x.bases,
        fires_inside: x.fireValid === x.bases ? x.fireInside : null,
        fires_within_10km: x.fireValid === x.bases ? x.fireNearby : null,
        total_frp_10km: x.fireValid === x.bases ? x.frp : null,
        pm2_5: x.pmWeight ? x.pmWeighted / x.pmWeight : null,
        source: 'Company summary from saved supply-base snapshot'
    }));
}

function renderRanks() {
    const kind = mode;
    const byCompany = $('group').value === 'company';
    const company = $('company-filter').value;

    let rows = byCompany
        ? aggregated(rankings[kind], kind)
        : rankings[kind];

    if (company) {
        rows = rows.filter(r => r.Company === company);
    }

    rows = [...rows].sort((a, b) => {
        if (kind === 'fire') {
            const key = r => [
                number(r.fires_inside),
                number(r.fires_within_10km),
                number(r.total_frp_10km)
            ];

            const x = key(a);
            const y = key(b);

            for (let i = 0; i < 3; i++) {
                const dif = (y[i] ?? -1) - (x[i] ?? -1);
                if (dif) return dif;
            }

            return 0;
        }

        return (number(b.pm2_5) ?? -1) -
               (number(a.pm2_5) ?? -1);
    });

    $('rank-list').innerHTML = rows.length
        ? rows.map((r, i) => {
            const val = kind === 'fire'
                ? number(r.fires_within_10km)
                : number(r.pm2_5);

            const metric = val === null
                ? 'N/A'
                : kind === 'fire'
                    ? fmt(val) + ' hotspots'
                    : fmt(val, 1) + ' µg/m³';

            const detail = kind === 'fire'
                ? 'Inside: ' +
                  (number(r.fires_inside) === null
                      ? 'N/A'
                      : fmt(r.fires_inside)) +
                  ' · FRP: ' +
                  (number(r.total_frp_10km) === null
                      ? 'N/A'
                      : fmt(r.total_frp_10km, 1)) +
                  ' MW'
                : 'Regional modelled PM2.5 · screening only';

            return `
                <article class="rank-card">
                    <div class="rank-number">#${i + 1}</div>
                    <div class="rank-info">
                        <strong>${esc(r.SupplyBase)}</strong>
                        <span>
                            ${esc(r.Company)}
                            ${byCompany ? ' · ' + r.bases + ' bases' : ''}
                        </span>
                        <small>${esc(detail)}</small>
                    </div>
                    <div class="rank-value">${metric}</div>
                </article>
            `;
        }).join('')
        : '<div class="empty">No records for this selection.</div>';
}


async function loadLayers() {

    // ========================================
    // 1. Load Map Data
    // ========================================

    const [estates, points, fires, hazeInfo] = await Promise.all([
        get('estates.geojson'),
        get('points.geojson'),
        get('fires.json'),
        get('haze_overlay.json')
    ]);

    const names = [
        ...new Set(
            [...estates.features, ...points.features]
                .map(f => f.properties?.Company)
                .filter(Boolean)
        )
    ].sort();

    const container = $('company-layers');
    container.replaceChildren();
    companyLayers.clear();

    const renderer = L.canvas({ padding: 0.5 });

    // ========================================
    // 2. Estate Boundaries + Palm Tree Markers
    // ========================================

    for (const name of names) {

        const color = companyColor(name);

        // Estate Boundaries
        const bounds = L.geoJSON({
            type: 'FeatureCollection',
            features: estates.features.filter(
                f => f.properties?.Company === name
            )
        }, {
            renderer,
            style: () => ({
                color: color,
                weight: 1.5,
                fillColor: color,
                fillOpacity: 0.25
            }),
            onEachFeature: (f, layer) => {
                layer.bindPopup(`
                    <b>${esc(f.properties?.SupplyBase || 'Estate')}</b>
                    <br>${esc(f.properties?.Company || name)}
                    <br>Plantation boundary
                `);
            }
        });

        // Palm Tree GPS Reference Points
        const refs = L.geoJSON({
            type: 'FeatureCollection',
            features: points.features.filter(
                f => f.properties?.Company === name
            )
        }, {
            pointToLayer: (feature, latlng) => {
                return L.marker(latlng, {
                    icon: L.divIcon({
                        className: 'estate-tree-icon',
                        html: `
                            <div style="
                                font-size: 22px;
                                line-height: 1;
                                text-align: center;
                                filter: drop-shadow(0 1px 2px #ffffff);
                            ">🌴</div>
                        `,
                        iconSize: [26, 26],
                        iconAnchor: [13, 13],
                        popupAnchor: [0, -13]
                    })
                });
            },

            onEachFeature: (feature, layer) => {
                const p = feature.properties || {};

                layer.bindPopup(`
                    <b>${esc(p.Estate_Name || 'Estate Reference')}</b>
                    <br>${esc(p.Company || name)}
                    <br>Coordinate basis:
                    ${esc(p.coordinate_basis || 'Reference point')}
                `);
            }
        });

        // Company Checkbox
        const label = document.createElement('label');
        label.className = 'company-layer-item';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = true;

        const swatch = document.createElement('span');
        swatch.className = 'company-swatch';
        swatch.style.backgroundColor = color;

        const text = document.createElement('span');
        text.textContent = name;

        label.append(checkbox, swatch, text);
        container.append(label);

        companyLayers.set(name, {
            boundaries: bounds,
            points: refs,
            checkbox
        });

        checkbox.addEventListener(
            'change',
            syncCompanies
        );
    }

    syncCompanies();

    // ========================================
    // 3. Fire Detection Points
    // ========================================

    fireLayer.clearLayers();

    for (const r of fires) {

        const lat = number(r.latitude);
        const lon = number(r.longitude);

        if (lat === null || lon === null) {
            continue;
        }

        L.circleMarker([lat, lon], {
            renderer,
            radius: 2.7,
            stroke: false,
            fillColor: '#E53935',
            fillOpacity: 0.68
        })
        .bindPopup(`
            <strong>NASA Thermal Detection</strong>
            <br>FRP: ${esc(r.frp ?? 'N/A')} MW
            <br>Date: ${esc(r.acq_date || 'Unknown')}
        `)
        .addTo(fireLayer);
    }

    // ========================================
    // 4. Continuous Haze Overlay
    // ========================================

    hazeLayer.clearLayers();

    if (
        !Array.isArray(hazeInfo.bounds) ||
        hazeInfo.bounds.length !== 2
    ) {
        throw new Error(
            'Invalid haze_overlay.json bounds'
        );
    }

    const hazeImage = L.imageOverlay(
        'data/haze_overlay.png?v=' + Date.now(),
        hazeInfo.bounds,
        {
            pane: 'hazePane',
            opacity: 1,
            interactive: false,
            className: 'haze-image-overlay'
        }
    );

    hazeImage.on('error', () => {
        console.error(
            'Could not load haze_overlay.png'
        );
    });

    hazeLayer.addLayer(hazeImage);

    // ========================================
    // 5. Map Layer Controls
    // ========================================

    $('boundaries').addEventListener(
        'change',
        syncCompanies
    );

    $('references').addEventListener(
        'change',
        syncCompanies
    );

    $('companies-all').addEventListener(
        'click',
        () => {
            for (const layers of companyLayers.values()) {
                layers.checkbox.checked = true;
            }

            syncCompanies();
        }
    );

    $('companies-none').addEventListener(
        'click',
        () => {
            for (const layers of companyLayers.values()) {
                layers.checkbox.checked = false;
            }

            syncCompanies();
        }
    );

    $('fire-map').addEventListener(
        'change',
        syncOverlay
    );

    $('haze-map').addEventListener(
        'change',
        syncOverlay
    );

    syncOverlay();

    // Adjust map size after initialization
    requestAnimationFrame(() => {
        map.invalidateSize();
    });
}


async function init() {
    setupMap();

    $('fire-btn').addEventListener('click', () => modeSet('fire'));
    $('haze-btn').addEventListener('click', () => modeSet('haze'));
    $('group').addEventListener('change', renderRanks);
    $('company-filter').addEventListener('change', renderRanks);

    try {
        const [meta, r] = await Promise.all([
            get('meta.json'),
            get('rankings.json')
        ]);

        rankings = r;

        const companies = [
            ...new Set([
                ...meta.companies,
                ...r.fire.map(x => x.Company),
                ...r.haze.map(x => x.Company)
            ])
        ].sort();

        $('company-filter').innerHTML =
            '<option value="">All companies</option>' +
            companies.map(x =>
                `<option value="${esc(x)}">${esc(x)}</option>`
            ).join('');

        $('companies').textContent = companies.length;

        const bases = new Set(
            [...r.fire, ...r.haze].map(
                x => x.Company + '\0' + x.SupplyBase
            )
        );

        $('bases').textContent = bases.size;

        for (const k of ['fire', 'haze']) {
            const available = r[k].filter(x =>
                k === 'fire'
                    ? x.fire_coverage_status === 'complete' &&
                      number(x.fires_within_10km) !== null
                    : number(x.pm2_5) !== null &&
                      number(x.coverage_pct) >= 90
            ).length;

            $(k + '-available').textContent =
                available + ' / ' + bases.size;
        }

        $('fire-status').textContent =
            fmt(meta.fire_count) + ' points';

        $('haze-status').textContent =
            fmt(meta.haze_samples) + ' cells';

        $('fire-updated').textContent =
            'Latest detection: ' +
            (meta.fire_detection_date || 'Unknown');

        $('haze-updated').textContent =
            'Model time: ' +
            (meta.haze_model_time || 'Unknown');

        $('snapshot').textContent =
            'Saved snapshots · ' +
            (meta.fire_saved_at?.slice(0, 10) || 'Date unknown');

        modeSet('fire');
        await loadLayers();

    } catch (err) {
        $('rank-list').innerHTML = `
            <div class="empty">
                Could not load web/data.
                Run the local server described in README.md.
                (${esc(err.message)})
            </div>
        `;
        console.error(err);
    }
}

init();


/* =========================================
   Automatic Update + Manual Refresh
   ========================================= */

const refreshButton = document.getElementById(
    "refresh-data-btn"
);

const refreshStatus = document.getElementById(
    "update-status"
);

let manualRefreshRequested = false;
let refreshInProgress = false;

function setUpdateStatus(message, type = "") {
    if (!refreshStatus) return;

    refreshStatus.textContent = message;
    refreshStatus.className = "update-status " + type;
}

function saveMapView() {
    if (typeof map === "undefined" || !map) return;

    const center = map.getCenter();

    sessionStorage.setItem(
        "fireHazeMapView",
        JSON.stringify({
            lat: center.lat,
            lng: center.lng,
            zoom: map.getZoom()
        })
    );
}

function restoreMapView() {
    if (typeof map === "undefined" || !map) return;

    const saved = sessionStorage.getItem(
        "fireHazeMapView"
    );

    if (!saved) return;

    try {
        const view = JSON.parse(saved);

        map.setView(
            [view.lat, view.lng],
            view.zoom,
            { animate: false }
        );

        sessionStorage.removeItem(
            "fireHazeMapView"
        );
    } catch (error) {
        console.warn("Could not restore map view:", error);
    }
}

async function checkUpdateStatus() {
    try {
        const response = await fetch(
            "/api/status",
            { cache: "no-store" }
        );

        if (!response.ok) {
            throw new Error("Status HTTP " + response.status);
        }

        const data = await response.json();

        if (
            data.state === "updating" ||
            data.state === "queued"
        ) {
            setUpdateStatus("Updating Fire & Haze...");

            refreshInProgress = true;
            refreshButton.disabled = true;

            return;
        }

        refreshButton.disabled = false;

        if (data.state === "success") {
            const time = data.last_success
                ? new Date(data.last_success)
                    .toLocaleString()
                : "Unknown";

            setUpdateStatus(
                "Last updated: " + time,
                "success"
            );

            if (manualRefreshRequested) {
                manualRefreshRequested = false;

                // Preserve map centre and zoom.
                saveMapView();

                // Reload JSON, ranking and map layers.
                window.location.reload();
            }

            refreshInProgress = false;
            return;
        }

        if (data.state === "failed") {
            setUpdateStatus(
                "Update failed — previous data retained",
                "error"
            );

            if (manualRefreshRequested) {
                console.error(data.last_error);
                manualRefreshRequested = false;
            }

            refreshInProgress = false;
            return;
        }

        setUpdateStatus("Waiting for next update");

    } catch (error) {
        setUpdateStatus(
            "Update server unavailable",
            "error"
        );

        console.error("Update status error:", error);
    }
}

async function manualRefresh() {
    if (refreshInProgress) return;

    const token = window.prompt(
        "Enter Admin Token to refresh Fire & Haze data:"
    );

    if (!token) return;

    refreshButton.disabled = true;
    setUpdateStatus("Starting refresh...");

    try {
        const response = await fetch(
            "/api/refresh",
            {
                method: "POST",
                headers: {
                    "X-Admin-Token": token
                },
                cache: "no-store"
            }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                result.detail ||
                result.message ||
                "Refresh request failed"
            );
        }

        manualRefreshRequested = true;
        refreshInProgress = true;

        setUpdateStatus(
            "Refreshing NASA FIRMS & PM2.5..."
        );

        await checkUpdateStatus();

    } catch (error) {
        setUpdateStatus(error.message, "error");
        console.error(error);
        refreshButton.disabled = false;
        refreshInProgress = false;
    }
}

if (refreshButton) {
    refreshButton.addEventListener(
        "click",
        manualRefresh
    );
}

// Restore map view after browser reload.
if (typeof map !== "undefined" && map) {
    map.whenReady(restoreMapView);
}

// Poll server status every 5 seconds.
checkUpdateStatus();

setInterval(checkUpdateStatus, 5000);
