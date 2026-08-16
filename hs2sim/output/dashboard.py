"""A self-contained interactive timeline of the mission, as one HTML file.

The PNG timeline answers "what happened in orbit 24" only if you already know
to look at orbit 24. This is the same data made browsable: pick a geometry,
scrub through the orbits, and read every series against a shared cursor.

The page is written as a single file with the data inlined, so it opens from
disk with no server and no network. Everything each orbit needs is resampled
onto one common grid of ``GRID_POINTS`` samples spanning a nominal orbit, which
is what lets the charts share an x axis and keeps the payload to a few MB
rather than the tens the raw 5 s history would cost.
"""

from __future__ import annotations

import json
import pathlib

import numpy as np

from .. import comms
from ..config import MissionConfig
from ..conops import MODE_EXPERIMENT, MODE_NAMES, ConopsResult
from ..environment import EnvironmentResult
from . import globe
from .style import MODE_WASH
from .timeline import orbit_segments

# Samples per orbit on the shared grid. Well past the pixel width any chart
# gets, so nothing visible is lost, and small enough to inline.
GRID_POINTS = 220


def _resample(minutes: np.ndarray, values: np.ndarray,
              grid: np.ndarray, categorical: bool = False) -> list:
    """One orbit's series onto the common grid; ``None`` outside its span.

    Partial orbits at the ends of the run really do lack data outside their
    span, and a gap is the honest way to draw that -- interpolating to the edge
    would invent a vehicle that was never propagated.
    """
    if minutes.size == 0:
        return [None] * grid.size
    if categorical:
        index = np.clip(np.searchsorted(minutes, grid), 0, minutes.size - 1)
        out = values[index]
    else:
        out = np.interp(grid, minutes, values)
    inside = (grid >= minutes[0] - 1e-9) & (grid <= minutes[-1] + 1e-9)
    return [None if not ok else (int(v) if categorical else round(float(v), 4))
            for ok, v in zip(inside, out)]


def _orbit_payload(cfg: MissionConfig, env: EnvironmentResult,
                   flown: ConopsResult, segments, grid: np.ndarray,
                   store: dict[str, np.ndarray], link_kbps: np.ndarray,
                   access: np.ndarray, downlinked_mb: np.ndarray) -> list[dict]:
    dt = env.dt_s
    queue_mb = flown.queue_bytes / 1e6
    net_w = flown.generation_w - flown.load_w
    images = flown.experiments * int(cfg.payload.n_cameras)
    cumulative_images = np.cumsum(images)
    eclipse = (env.shadow_factor < 0.5).astype(int)

    orbits = []
    for number, (start, stop, t_ref) in enumerate(segments, start=1):
        minutes = (env.t_s[start:stop] - t_ref) / 60.0
        span = slice(start, stop)
        sent = float(flown.downlinked_bytes[span].sum() / 1e6)
        orbits.append({
            "n": number,
            "t_start_h": round(float(env.t_s[start]) / 3600.0, 3),
            "gen": _resample(minutes, flown.generation_w[span], grid),
            "load": _resample(minutes, flown.load_w[span], grid),
            "net": _resample(minutes, net_w[span], grid),
            "soc": _resample(minutes, flown.soc[span] * 100.0, grid),
            "mode": _resample(minutes, flown.mode[span], grid, categorical=True),
            "eclipse": _resample(minutes, eclipse[span], grid, categorical=True),
            "queue": _resample(minutes, queue_mb[span], grid),
            "stored": _resample(minutes, store["stored_gb"][span], grid),
            "unproc": _resample(minutes, store["unprocessed_gb"][span], grid),
            "proc": _resample(minutes, store["processed_gb"][span], grid),
            "sent": _resample(minutes, downlinked_mb[span], grid),
            "link": _resample(minutes, link_kbps[span], grid),
            "access": _resample(minutes, access[span], grid, categorical=True),
            "stats": {
                "min_soc": round(float(flown.soc[span].min() * 100.0), 1),
                "max_soc": round(float(flown.soc[span].max() * 100.0), 1),
                "images": int(round(float(images[span].sum()))),
                # Mission-to-date, so scrubbing shows the total accumulating
                # rather than only what this one orbit managed.
                "images_to_date": int(round(float(cumulative_images[stop - 1]))),
                "sent_mb": round(sent, 3),
                "eclipse_min": round(float(eclipse[span].sum()) * dt / 60.0, 1),
                # Straight off the mode history rather than a fraction times a
                # nominal period: the orbits at either end of the run are
                # partial, and their fraction would be of the wrong duration.
                "experiment_min": round(
                    float(np.sum(flown.mode[span] == MODE_EXPERIMENT))
                    * dt / 60.0, 1),
                "fractions": {
                    MODE_NAMES[code]: round(
                        float(np.mean(flown.mode[span] == code)), 4)
                    for code in MODE_NAMES
                },
            },
        })
    return orbits


def build(cfg: MissionConfig, env: EnvironmentResult, results: dict,
          timelines: dict[str, ConopsResult],
          out_dir: pathlib.Path) -> pathlib.Path:
    """Write ``mission_dashboard.html`` and return its path."""
    period_min = float(results["orbit"]["orbit_period_min"])
    segments = orbit_segments(env, period_min * 60.0)
    grid = np.linspace(0.0, period_min, GRID_POINTS)

    # Link rate and station access are properties of the orbit, not of the
    # geometry, but they belong beside the data curves so they are carried per
    # sample here rather than recomputed in the page.
    ranges = np.where(env.station_access, env.station_range, np.inf)
    visible = np.isfinite(np.min(ranges, axis=0))
    best_range = np.where(visible, np.min(ranges, axis=0), 1e12)
    link_kbps = np.where(visible,
                         comms.achievable_bitrate_bps(cfg, best_range) / 1e3,
                         0.0)
    access = visible.astype(int)

    image_bytes = comms.image_bytes(cfg)
    n_cameras = int(cfg.payload.n_cameras)
    storage_gb = float(cfg.payload.storage_gb)

    payload = {
        "meta": {
            "period_min": round(period_min, 3),
            "days": round(float(env.duration_days), 3),
            "dt_s": float(env.dt_s),
            "capacity_wh": float(cfg.spacecraft.battery.capacity_wh),
            "storage_gb": storage_gb,
            "grid": [round(float(v), 3) for v in grid],
            "orbit_count": len(segments),
            "eclipse_fraction": round(
                float(results["orbit"]["eclipse_fraction"]), 4),
            "passes_per_day": round(
                float(results["comms"]["aggregate"]["passes_per_day"]), 1),
        },
        "modeColors": {name: MODE_WASH[name] for name in MODE_WASH},
        "geometries": {},
    }

    for name, flown in timelines.items():
        # The on-board image store, from the model in `storage`: frames are
        # captured far faster than the OBC reduces them, and a reduced frame
        # still occupies the disk until its retention runs out. So this is
        # three curves, not a running total of everything ever taken.
        st = flown.store
        if st is not None:
            store = {
                "stored_gb": st.stored_bytes / 1e9,
                "unprocessed_gb": st.unprocessed_images * st.image_bytes / 1e9,
                "processed_gb": st.processed_images * st.image_bytes / 1e9,
            }
            store_stats = st.summary(env)
        else:
            zeros = np.zeros(env.n_samples)
            store = {"stored_gb": zeros, "unprocessed_gb": zeros,
                     "processed_gb": zeros}
            store_stats = {}
        downlinked_mb = np.cumsum(flown.downlinked_bytes) / 1e6
        total_images = float(np.sum(flown.experiments)) * n_cameras

        entry = results["geometries"].get(name, {})
        baseline = entry.get("conops_baseline", {})
        budget = flown.budget
        payload["geometries"][name] = {
            "description": str(entry.get("description", "")),
            "thresholds": {
                "safe": round(budget.soc_safe * 100.0, 2) if budget else None,
                "standby": round(budget.soc_standby * 100.0, 2) if budget else None,
                "experiment": round(budget.soc_experiment * 100.0, 2) if budget else None,
                "floor": round(
                    (1.0 - float(cfg.spacecraft.battery.depth_of_discharge_limit))
                    * 100.0, 2),
            },
            "summary": {
                "images_total": int(round(total_images)),
                "experiments_total": int(round(float(np.sum(flown.experiments)))),
                # The payload cadence is a free parameter, so the counts scale
                # with it and the time on target does not. Both are reported.
                "experiment_hours": round(
                    float(baseline.get("experiment_hours_total", 0.0)), 2),
                "experiment_min_per_day": round(
                    float(baseline.get("experiment_min_per_day", 0.0)), 0),
                "experiment_block_median_min": round(
                    float(baseline.get("experiment_block_median_min", 0.0)), 1),
                "payload_rate_hz": float(
                    cfg.mission.analysis.payload_rate_hz),
                "images_per_day": round(float(baseline.get("images_per_day", 0)), 0),
                "downlinked_mb_per_day": round(
                    float(baseline.get("downlinked_mb_per_day", 0)), 2),
                "min_soc": round(float(baseline.get("min_soc", 0)) * 100.0, 1),
                "energy_margin_w": round(
                    float(baseline.get("energy_margin_w", 0)), 2),
                "slews_per_day": round(float(baseline.get("slews_per_day", 0)), 0),
                "slews_abandoned": int(baseline.get("slews_abandoned", 0)),
                "mission_failed": bool(baseline.get("mission_failed", False)),
                "final_storage_gb": round(float(store["stored_gb"][-1]), 3),
                "peak_storage_gb": round(float(np.max(store["stored_gb"])), 3),
                "images_processed": int(round(
                    store_stats.get("images_processed", 0.0))),
                "images_purged": int(round(
                    store_stats.get("images_purged", 0.0))),
                "images_dropped": int(round(
                    store_stats.get("images_dropped_store_full", 0.0))),
                "backlog_final": int(round(
                    store_stats.get("processing_backlog_final", 0.0))),
                "backlog_growth_per_day": int(round(
                    store_stats.get("unprocessed_growth_images_per_day", 0.0))),
            },
            "orbits": _orbit_payload(cfg, env, flown, segments, grid,
                                     store, link_kbps, access, downlinked_mb),
        }

    payload["meta"]["processing_period_s"] = float(
        cfg.payload.processing_period_s)
    payload["meta"]["retention_h"] = float(cfg.payload.processed_retention_h)
    payload["meta"]["processing_images_per_day"] = round(
        n_cameras * 86400.0 / float(cfg.payload.processing_period_s), 0)
    payload["meta"]["image_mb"] = round(image_bytes / 1e6, 3)
    payload["viz"] = globe.payload(cfg, env, timelines, segments, period_min)

    out_dir.mkdir(exist_ok=True)
    path = out_dir / "mission_dashboard.html"
    html = (_TEMPLATE
            .replace("/*__GLOBE_STYLE__*/", globe.STYLE)
            .replace("<!--__GLOBE_MARKUP__-->", globe.MARKUP)
            .replace("/*__GLOBE_SCRIPT__*/", globe.SCRIPT)
            .replace("/*__DATA__*/null",
                     json.dumps(payload, separators=(",", ":"),
                                allow_nan=False)))
    path.write_text(html, encoding="utf-8")
    return path


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HS-2 mission timeline</title>
<style>
:root{
  color-scheme: light;
  --surface:#fcfcfb; --panel:#ffffff; --plane:#f4f4f1;
  --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --accent:#2a78d6; --crit:#d03b3b;
  --shadow:0 1px 2px rgba(11,11,11,.06),0 4px 16px rgba(11,11,11,.05);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme=light]){
    color-scheme: dark;
    --surface:#1a1a19; --panel:#212120; --plane:#0d0d0d;
    --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --accent:#3987e5; --crit:#d03b3b;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 4px 16px rgba(0,0,0,.35);
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:20;background:var(--surface);
  border-bottom:1px solid var(--grid);padding:14px 20px 12px}
h1{margin:0 0 2px;font-size:16px;font-weight:600;letter-spacing:-.01em}
.sub{color:var(--ink2);font-size:12px}
.bar{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-top:12px}
.tabs{display:flex;gap:4px;background:var(--plane);padding:3px;border-radius:8px}
.tab{border:0;background:transparent;color:var(--ink2);padding:5px 12px;
  border-radius:6px;font:inherit;font-size:12px;cursor:pointer}
.tab[aria-selected=true]{background:var(--panel);color:var(--ink);
  font-weight:600;box-shadow:var(--shadow)}
.scrub{flex:1;min-width:260px;display:flex;align-items:center;gap:10px}
input[type=range]{flex:1;accent-color:var(--accent)}
button.step{border:1px solid var(--axis);background:var(--panel);color:var(--ink);
  width:30px;height:28px;border-radius:6px;cursor:pointer;font:inherit}
button.step:hover{border-color:var(--accent);color:var(--accent)}
.ocount{font-variant-numeric:tabular-nums;color:var(--ink2);font-size:12px;
  min-width:112px}
main{padding:18px 20px 60px;max-width:1180px;margin:0 auto}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));
  gap:10px;margin-bottom:16px}
.tile{background:var(--panel);border:1px solid var(--grid);border-radius:10px;
  padding:10px 12px;box-shadow:var(--shadow)}
.tile .k{font-size:11px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.04em}
.tile .v{font-size:19px;font-weight:600;margin-top:2px;
  font-variant-numeric:tabular-nums}
.tile .u{font-size:11px;color:var(--ink2);font-weight:400}
.card{background:var(--panel);border:1px solid var(--grid);border-radius:10px;
  padding:12px 14px 6px;margin-bottom:12px;box-shadow:var(--shadow)}
.card h2{margin:0;font-size:13px;font-weight:600}
.card .note{font-size:11px;color:var(--muted);margin:1px 0 6px}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--ink2);
  margin:2px 0 6px}
.legend span{display:inline-flex;align-items:center;gap:5px}
.sw{width:10px;height:10px;border-radius:2px;display:inline-block}
.swl{width:14px;height:0;border-top:2px solid;display:inline-block}
svg{display:block;width:100%;overflow:visible}
.tt{position:fixed;pointer-events:none;z-index:40;background:var(--panel);
  border:1px solid var(--axis);border-radius:8px;padding:8px 10px;font-size:12px;
  box-shadow:var(--shadow);opacity:0;transition:opacity .08s}
.tt b{display:block;margin-bottom:4px;font-size:11px;color:var(--muted);
  text-transform:uppercase;letter-spacing:.04em}
.tt table{border-collapse:collapse}
.tt td{padding:1px 0}
.tt td.n{text-align:right;padding-left:12px;font-variant-numeric:tabular-nums}
.overview{margin-bottom:16px}
.overview .card{padding-bottom:10px}
footer{color:var(--muted);font-size:11px;padding:0 20px 30px;max-width:1180px;
  margin:0 auto}
kbd{background:var(--plane);border:1px solid var(--axis);border-radius:4px;
  padding:0 4px;font:inherit;font-size:11px}
.tile.total{background:linear-gradient(180deg,var(--panel),var(--plane))}
.tile.total .v{font-size:22px}
/*__GLOBE_STYLE__*/
</style>
</head>
<body>
<header>
  <h1>HS-2 mission timeline</h1>
  <div class="sub" id="sub"></div>
  <div class="bar">
    <div class="tabs" id="tabs" role="tablist"></div>
    <div class="scrub">
      <button class="step" id="prev" title="Previous orbit">&#8249;</button>
      <input type="range" id="slider" min="1" value="1" step="1">
      <button class="step" id="next" title="Next orbit">&#8250;</button>
      <span class="ocount" id="ocount"></span>
    </div>
  </div>
</header>
<main>
  <div class="overview"><div class="card">
    <h2>Whole mission</h2>
    <div class="note" id="ovnote">State of charge across every orbit. Click to
    jump.</div>
    <div id="overview"></div>
  </div></div>
  <div class="tiles" id="totals"></div>
  <!--__GLOBE_MARKUP__-->
  <div class="tiles" id="tiles"></div>
  <div id="charts"></div>
</main>
<footer>
  <kbd>&larr;</kbd> <kbd>&rarr;</kbd> step orbits &middot; drag the slider to
  scrub &middot; hover any chart for a shared cursor. Series are resampled onto
  a common grid, so gaps at the edges are partial orbits rather than missing
  data.
</footer>
<div class="tt" id="tt"></div>
<script>
const DATA = /*__DATA__*/null;
const M = DATA.meta, G = DATA.geometries, MC = DATA.modeColors;
const names = Object.keys(G);
let geo = names[0], orbit = 1, cursor = null;

const css = v => getComputedStyle(document.documentElement)
  .getPropertyValue(v).trim();
const fmt = (v, d = 1) => v === null || v === undefined || Number.isNaN(v)
  ? "—" : v.toFixed(d);

/* ---- chart specs. One measure per chart: no chart carries two y scales. -- */
const CHARTS = [
  {id:"power", title:"Power", unit:"W", note:"Generation against the load the "
    +"flown mode draws, and the balance the battery sees.",
   series:[{k:"gen",label:"generation",color:"#1baf7a"},
           {k:"load",label:"load",color:"#eb6834"},
           {k:"net",label:"generation − load",color:null,width:2}],
   zero:true},
  {id:"soc", title:"State of charge", unit:"%", note:"Against the mode-entry "
    +"thresholds this run was scheduled on.", series:[{k:"soc",label:"SOC",
    color:null,width:2}], thresholds:true, pad:6},
  {id:"storage", title:"On-board image store", unit:"GB", note:"", storage:true,
   series:[{k:"stored",label:"stored (total)",color:"#4a3aa7",width:2},
           {k:"unproc",label:"awaiting processing",color:"#eb6834"},
           {k:"proc",label:"processed, awaiting purge",color:"#1baf7a"}]},
  {id:"queue", title:"Downlink backlog", unit:"MB", note:"Data queued for the "
    +"next contact, and what has been sent since epoch.",
   series:[{k:"queue",label:"queued",color:"#eb6834",width:2},
           {k:"sent",label:"sent (cumulative)",color:"#2a78d6"}]},
  {id:"link", title:"Achievable link rate", unit:"kbit/s", note:"What the "
    +"budget closes at the current range; zero when no station is up.",
   series:[{k:"link",label:"link rate",color:"#2a78d6",width:2}]},
];

/* ---------------------------------------------------------------- layout - */
const PAD = {l:52, r:14, t:8, b:18}, H = 118, STRIP = 16, XAX = 14, W = 1000;

function xAt(i){ return PAD.l + (W - PAD.l - PAD.r) * (i / (M.grid.length - 1)); }
function iAtX(px){
  const f = (px - PAD.l) / (W - PAD.l - PAD.r);
  return Math.max(0, Math.min(M.grid.length - 1, Math.round(f * (M.grid.length - 1))));
}

function extent(o, spec){
  let lo = Infinity, hi = -Infinity;
  for (const s of spec.series) for (const v of o[s.k])
    if (v !== null){ if (v < lo) lo = v; if (v > hi) hi = v; }
  if (spec.thresholds){
    const t = G[geo].thresholds;
    for (const k of ["safe","standby","experiment"])
      if (t[k] !== null){ lo = Math.min(lo, t[k]); hi = Math.max(hi, t[k]); }
    hi = Math.max(hi, 100);
  }
  // Capacity is NOT forced into range: the store runs at a fraction of a
  // percent of it, so including it would flatten the curve to a flat line on
  // the axis. The line is drawn only if it is near the data, and the figure
  // is stated in the note either way.
  if (spec.storage && M.storage_gb <= hi * 1.5) hi = Math.max(hi, M.storage_gb);
  if (spec.zero){ lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (!isFinite(lo)){ lo = 0; hi = 1; }
  if (hi - lo < 1e-9) hi = lo + 1;
  const pad = (hi - lo) * 0.10;
  return [lo - pad, hi + pad];
}

function ticks(lo, hi, n = 4){
  const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

function path(o, key, lo, hi){
  const y = v => PAD.t + (H - PAD.t - PAD.b) * (1 - (v - lo) / (hi - lo));
  let d = "", pen = false;
  o[key].forEach((v, i) => {
    if (v === null){ pen = false; return; }
    d += (pen ? "L" : "M") + xAt(i).toFixed(1) + " " + y(v).toFixed(1) + " ";
    pen = true;
  });
  return d;
}

/* Contiguous runs of a categorical series, as [from, to, value]. */
function bands(arr){
  const out = []; let start = 0;
  for (let i = 1; i <= arr.length; i++){
    if (i === arr.length || arr[i] !== arr[start]){
      if (arr[start] !== null) out.push([start, i, arr[start]]);
      start = i;
    }
  }
  return out;
}

function modeStrip(o, width){
  let s = "";
  for (const [a, b, v] of bands(o.mode)){
    const name = ["safe","standby","slew","experiment","downlink"][v];
    s += `<rect x="${xAt(a).toFixed(1)}" y="0" width="${
      Math.max(1, xAt(b) - xAt(a)).toFixed(1)}" height="${STRIP}" fill="${
      MC[name]}" opacity="${name === "slew" ? .35 : .55}"><title>${name}</title></rect>`;
  }
  return s;
}

function eclipseBands(o, h){
  let s = "";
  for (const [a, b, v] of bands(o.eclipse)) if (v === 1)
    s += `<rect x="${xAt(a).toFixed(1)}" y="0" width="${
      Math.max(1, xAt(b) - xAt(a)).toFixed(1)}" height="${h}" fill="${
      css("--ink2")}" opacity=".07"/>`;
  return s;
}

/* Minutes since the ascending node, the x axis every chart shares. */
function xAxis(){
  const last = M.grid[M.grid.length - 1];
  let s = "";
  for (const t of ticks(0, last, 6)){
    if (t < 0 || t > last) continue;
    const px = PAD.l + (W - PAD.l - PAD.r) * (t / last);
    s += `<text x="${px.toFixed(1)}" y="10" text-anchor="middle" font-size="10"
      fill="${css("--muted")}">${(+t.toFixed(1))}</text>`;
  }
  return s;
}

function storageNote(){
  const s = G[geo].summary, cap = M.storage_gb;
  const used = s.final_storage_gb;
  return `Frames stay on board: only the 122-byte numerical product is `
    + `downlinked. The OBC reduces one FOUND and one LOST frame every `
    + `${(M.processing_period_s / 60).toFixed(0)} min `
    + `(${M.processing_images_per_day.toLocaleString()} frames/day), and a `
    + `reduced frame is purged ${M.retention_h.toFixed(0)} h later &mdash; so `
    + `the store holds both populations at once. Peak `
    + `${s.peak_storage_gb.toFixed(2)} GB of ${cap} GB `
    + `(${(100 * s.peak_storage_gb / cap).toFixed(2)} %); the axis follows the `
    + `data rather than the capacity line. Unprocessed backlog is `
    + (s.backlog_growth_per_day > 0
        ? `growing ${s.backlog_growth_per_day.toLocaleString()} frames/day.`
        : `not growing.`)
    + (s.images_dropped > 0
        ? ` <b>${s.images_dropped.toLocaleString()} frames were not taken for `
          + `want of room.</b>` : ``);
}

function chartSVG(o, spec){
  const [lo, hi] = extent(o, spec);
  const y = v => PAD.t + (H - PAD.t - PAD.b) * (1 - (v - lo) / (hi - lo));
  let g = "";
  for (const t of ticks(lo, hi)){
    g += `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(t).toFixed(1)}" y2="${
      y(t).toFixed(1)}" stroke="${css("--grid")}" stroke-width="1"/>`;
    g += `<text x="${PAD.l - 8}" y="${(y(t) + 3.5).toFixed(1)}" text-anchor="end"
      font-size="10" fill="${css("--muted")}">${
      Math.abs(t) >= 1000 ? t.toExponential(1) : (+t.toFixed(2))}</text>`;
  }
  if (spec.zero) g += `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(0).toFixed(1)}"
    y2="${y(0).toFixed(1)}" stroke="${css("--axis")}" stroke-width="1"/>`;
  if (spec.thresholds){
    const t = G[geo].thresholds;
    for (const [k, lbl] of [["safe","safe"],["standby","downlink"],
                            ["experiment","experiment"]]){
      if (t[k] === null || t[k] > hi || t[k] < lo) continue;
      g += `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(t[k]).toFixed(1)}"
        y2="${y(t[k]).toFixed(1)}" stroke="${css("--muted")}" stroke-width="1"
        stroke-dasharray="1 3"/>`;
      g += `<text x="${W - PAD.r}" y="${(y(t[k]) - 3).toFixed(1)}" text-anchor="end"
        font-size="9" fill="${css("--muted")}">${lbl} ${t[k].toFixed(0)}%</text>`;
    }
  }
  if (spec.storage && M.storage_gb <= hi && M.storage_gb >= lo)
    g += `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(M.storage_gb).toFixed(1)}"
      y2="${y(M.storage_gb).toFixed(1)}" stroke="${css("--crit")}"
      stroke-width="1" stroke-dasharray="4 3"/>`;

  let lines = "";
  for (const s of spec.series)
    lines += `<path d="${path(o, s.k, lo, hi)}" fill="none" stroke="${
      s.color || css("--ink")}" stroke-width="${s.width || 1.4}"
      stroke-linejoin="round"/>`;

  return `<svg viewBox="0 0 ${W} ${H + STRIP + XAX + 4}" preserveAspectRatio="none"
    style="height:${H + STRIP + XAX + 4}px" data-chart="${spec.id}">
    <g>${eclipseBands(o, H)}</g><g>${g}</g><g>${lines}</g>
    <g class="cursor"></g>
    <g transform="translate(0,${H + 4})">${modeStrip(o)}</g>
    <g transform="translate(0,${H + STRIP + 4})">${xAxis()}</g>
  </svg>`;
}

/*__GLOBE_SCRIPT__*/

/* ------------------------------------------------------------- rendering - */
function renderTabs(){
  document.getElementById("tabs").innerHTML = names.map(n =>
    `<button class="tab" role="tab" data-geo="${n}" aria-selected="${n === geo}">${
      n}</button>`).join("");
}

function renderTotals(){
  const s = G[geo].summary;
  const tiles = [
    ["Observing time, whole mission", s.experiment_hours.toFixed(1),
     `h · ${s.experiment_min_per_day.toFixed(0)} min/day`, 1],
    ["Experiments, whole mission", s.experiments_total.toLocaleString(),
     `at ${s.payload_rate_hz} Hz`, 1],
    ["Images, whole mission", s.images_total.toLocaleString(),
     `${M.days.toFixed(1)} days`, 1],
    ["Median observation", s.experiment_block_median_min.toFixed(1), "min", 0],
    ["Frames processed", s.images_processed.toLocaleString(), "on board", 0],
    ["Frames purged", s.images_purged.toLocaleString(),
     `after ${M.retention_h.toFixed(0)} h`, 0],
    ["Awaiting processing", s.backlog_final.toLocaleString(),
     "at end of run", 0],
    ["Store peak", s.peak_storage_gb.toFixed(2) + " / " + M.storage_gb, "GB", 0],
  ];
  document.getElementById("totals").innerHTML = tiles.map(([k, v, u, big]) =>
    `<div class="tile${big ? " total" : ""}"><div class="k">${k}</div>
     <div class="v">${v} <span class="u">${u}</span></div></div>`).join("");
}

function renderTiles(){
  const o = G[geo].orbits[orbit - 1], s = o.stats, sum = G[geo].summary;
  const f = s.fractions, pct = v => (v * 100).toFixed(0) + "%";
  const tiles = [
    ["Min SOC this orbit", fmt(s.min_soc), "%"],
    ["Observing this orbit", fmt(s.experiment_min), "min"],
    ["Images this orbit", s.images.toLocaleString(), ""],
    ["Images to date", s.images_to_date.toLocaleString(),
     `of ${sum.images_total.toLocaleString()}`],
    ["Downlinked", fmt(s.sent_mb, 2), "MB"],
    ["Eclipse", fmt(s.eclipse_min), "min"],
    ["Experiment", pct(f.experiment), "of orbit"],
    ["Slew", pct(f.slew), "of orbit"],
  ];
  document.getElementById("tiles").innerHTML = tiles.map(([k, v, u]) =>
    `<div class="tile"><div class="k">${k}</div><div class="v">${v} <span class="u">${
      u}</span></div></div>`).join("");
}

function renderCharts(){
  const o = G[geo].orbits[orbit - 1];
  document.getElementById("charts").innerHTML = CHARTS.map(spec => {
    const legend = spec.series.map(s =>
      `<span><i class="swl" style="border-color:${s.color || css("--ink")}"></i>${
        s.label}</span>`).join("")
      + (spec.storage ? `<span><i class="swl" style="border-color:${css("--crit")};
         border-top-style:dashed"></i>capacity</span>` : "");
    return `<div class="card" data-id="${spec.id}">
      <h2>${spec.title} <span class="u" style="color:var(--muted);font-weight:400">(${
        spec.unit})</span></h2>
      <div class="note">${spec.id === "storage" ? storageNote() : spec.note}</div>
      <div class="legend">${legend}</div>
      ${chartSVG(o, spec)}
    </div>`;
  }).join("")
  + `<div class="card"><h2>Mode</h2>
     <div class="note">The strip under every chart above, in full. Every x
     axis on this page is minutes since the ascending node, so the same
     instant sits at the same place in all of them.</div>
     <div class="legend">${Object.keys(MC).map(n =>
       `<span><i class="sw" style="background:${MC[n]}"></i>${n}</span>`).join("")}
       <span><i class="sw" style="background:${css("--ink2")};opacity:.25"></i>eclipse</span>
     </div>
     <svg viewBox="0 0 ${W} 26" preserveAspectRatio="none" style="height:26px">
       ${eclipseBands(G[geo].orbits[orbit - 1], 26)}
       <g transform="translate(0,4)">${modeStrip(G[geo].orbits[orbit - 1])}</g>
     </svg></div>`;
  attachHover();
}

function renderOverview(){
  const orbits = G[geo].orbits, n = orbits.length;
  const h = 54, w = W;
  let mins = [], maxs = [];
  orbits.forEach(o => {
    const vals = o.soc.filter(v => v !== null);
    mins.push(Math.min(...vals)); maxs.push(Math.max(...vals));
  });
  const lo = Math.min(...mins) - 3, hi = Math.max(...maxs) + 3;
  const y = v => h * (1 - (v - lo) / (hi - lo));
  const x = i => (w * i) / n;
  let bars = "";
  for (let i = 0; i < n; i++){
    bars += `<rect x="${x(i).toFixed(1)}" y="${y(maxs[i]).toFixed(1)}" width="${
      Math.max(1, w / n - 1).toFixed(1)}" height="${
      Math.max(1, y(mins[i]) - y(maxs[i])).toFixed(1)}" rx="1"
      fill="${i + 1 === orbit ? css("--accent") : css("--axis")}"
      data-orbit="${i + 1}"><title>orbit ${i + 1}: ${mins[i].toFixed(1)}–${
      maxs[i].toFixed(1)}% SOC</title></rect>`;
  }
  const t = G[geo].thresholds, lines = ["safe","standby","experiment"]
    .filter(k => t[k] !== null && t[k] >= lo && t[k] <= hi)
    .map(k => `<line x1="0" x2="${w}" y1="${y(t[k]).toFixed(1)}" y2="${
      y(t[k]).toFixed(1)}" stroke="${css("--muted")}" stroke-dasharray="1 3"/>`)
    .join("");
  document.getElementById("overview").innerHTML =
    `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="height:${h}px"
      id="ovsvg">${lines}${bars}</svg>`;
  document.getElementById("ovsvg").onclick = e => {
    const n = e.target.getAttribute("data-orbit");
    if (n) setOrbit(+n);
  };
}

/* ------------------------------------------------------------ interaction */
const tt = document.getElementById("tt");

function attachHover(){
  const cards = [...document.querySelectorAll("#charts svg[data-chart]")];
  const all = [...document.querySelectorAll("#charts svg")];
  const move = e => {
    const svg = e.currentTarget, r = svg.getBoundingClientRect();
    const i = iAtX(((e.clientX - r.left) / r.width) * W);
    cursor = i; drawCursor(all); showTip(e, i); globeFollowCursor(i);
  };
  const leave = () => { cursor = null; drawCursor(all); tt.style.opacity = 0; };
  all.forEach(s => { s.onmousemove = move; s.onmouseleave = leave; });
}

function drawCursor(all){
  all.forEach(svg => {
    const g = svg.querySelector(".cursor");
    if (!g) return;
    g.innerHTML = cursor === null ? "" :
      `<line x1="${xAt(cursor).toFixed(1)}" x2="${xAt(cursor).toFixed(1)}"
        y1="${PAD.t}" y2="${H - PAD.b}" stroke="${css("--accent")}"
        stroke-width="1" stroke-dasharray="2 2"/>`;
  });
}

function showTip(e, i){
  const o = G[geo].orbits[orbit - 1];
  const mode = o.mode[i] === null ? "—"
    : ["safe","standby","slew","experiment","downlink"][o.mode[i]];
  const rows = [
    ["mode", mode], ["eclipse", o.eclipse[i] ? "yes" : "no"],
    ["generation", fmt(o.gen[i], 2) + " W"], ["load", fmt(o.load[i], 2) + " W"],
    ["net", fmt(o.net[i], 2) + " W"], ["SOC", fmt(o.soc[i], 1) + " %"],
    ["stored", fmt(o.stored[i], 3) + " GB"],
    ["backlog", fmt(o.queue[i], 3) + " MB"],
    ["link", fmt(o.link[i], 0) + " kbit/s"],
    ["station up", o.access[i] ? "yes" : "no"],
  ];
  tt.innerHTML = `<b>t + ${fmt(M.grid[i], 1)} min &middot; orbit ${orbit}</b>
    <table>${rows.map(([k, v]) =>
      `<tr><td>${k}</td><td class="n">${v}</td></tr>`).join("")}</table>`;
  tt.style.opacity = 1;
  const w = tt.offsetWidth, h = tt.offsetHeight;
  tt.style.left = Math.min(window.innerWidth - w - 12, e.clientX + 16) + "px";
  tt.style.top = Math.min(window.innerHeight - h - 12,
    Math.max(8, e.clientY - h / 2)) + "px";
}

function setOrbit(n){
  const max = G[geo].orbits.length;
  orbit = Math.max(1, Math.min(max, n));
  document.getElementById("slider").value = orbit;
  const o = G[geo].orbits[orbit - 1];
  document.getElementById("ocount").textContent =
    `orbit ${orbit} / ${max} · t+${o.t_start_h.toFixed(2)} h`;
  renderTiles(); renderCharts(); renderOverview(); renderGlobe();
}

function setGeo(n){
  geo = n; renderTabs(); renderTotals();
  document.getElementById("slider").max = G[geo].orbits.length;
  setOrbit(Math.min(orbit, G[geo].orbits.length));
}

document.getElementById("tabs").onclick = e => {
  const n = e.target.getAttribute("data-geo"); if (n) setGeo(n);
};
document.getElementById("slider").oninput = e => setOrbit(+e.target.value);
document.getElementById("prev").onclick = () => setOrbit(orbit - 1);
document.getElementById("next").onclick = () => setOrbit(orbit + 1);
addEventListener("keydown", e => {
  if (e.key === "ArrowLeft"){ setOrbit(orbit - 1); e.preventDefault(); }
  if (e.key === "ArrowRight"){ setOrbit(orbit + 1); e.preventDefault(); }
});

document.getElementById("sub").textContent =
  `${M.days.toFixed(1)} days · ${M.orbit_count} orbits · `
  + `${M.period_min.toFixed(1)} min period · `
  + `${(M.eclipse_fraction * 100).toFixed(0)} % eclipse · `
  + `${M.passes_per_day} passes/day`;
document.getElementById("slider").max = G[geo].orbits.length;
renderTabs(); renderTotals(); setOrbit(1);
</script>
</body>
</html>
"""
