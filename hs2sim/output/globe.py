"""The Vizard scene, rebuilt inside the dashboard page.

``output.vizard`` writes a real Vizard binary, which is the right tool for
looking at this mission -- but it needs Basilisk, a Vizard install and a
separate window, so it cannot sit next to the charts. This module renders the
same scene into the HTML page instead: the Earth turning under the orbit, the
Sun and the terminator, the ground stations, and the spacecraft flying the
attitude the scheduler actually chose, with the FOUND and LOST boresights drawn
where they were pointed.

It is deliberately plain: a hand-rolled orthographic projection onto a 2D
canvas, no WebGL and no libraries, so the page stays a single self-contained
file that opens from disk. What it gives up in shading it keeps in being
checkable -- every vector drawn is one the simulation computed.

The scene is sampled at ``VIZ_POINTS`` per orbit rather than the chart grid's
220: attitude is nine numbers a sample and this is a view, not a measurement.
Positions and Sun directions are shared across geometries because they are
properties of the orbit; only the attitude differs between them.
"""

from __future__ import annotations

import numpy as np

from ..config import MissionConfig
from ..conops import ConopsResult
from ..environment import R_EARTH, EnvironmentResult

# Scene samples per orbit. At a 92 min period this is a frame every 77 s, which
# is smooth enough to read a slew by eye without inlining attitude at full rate.
VIZ_POINTS = 72


def _indices(minutes: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Nearest real sample for each grid minute, or -1 outside the orbit's span.

    Nearest sample rather than interpolation: two of the things carried here
    are rotation matrices, and interpolating those component-wise would hand
    the page frames that are not rotations at all.
    """
    if minutes.size == 0:
        return np.full(grid.size, -1, dtype=int)
    idx = np.clip(np.searchsorted(minutes, grid), 0, minutes.size - 1)
    inside = (grid >= minutes[0] - 1e-9) & (grid <= minutes[-1] + 1e-9)
    return np.where(inside, idx, -1)


def _flat(values: np.ndarray, digits: int) -> list[float]:
    return [round(float(v), digits) for v in np.asarray(values).reshape(-1)]


def payload(cfg: MissionConfig, env: EnvironmentResult,
            timelines: dict[str, ConopsResult], segments,
            period_min: float) -> dict:
    """Scene data for every orbit, plus per-geometry attitude."""
    grid = np.linspace(0.0, period_min, VIZ_POINTS)

    sun_hat = env.sun_unit()
    eclipse = (env.shadow_factor < 0.5).astype(int)
    ranges = np.where(env.station_access, env.station_range, np.inf)
    best = np.argmin(ranges, axis=0)
    visible = np.isfinite(np.min(ranges, axis=0))
    station_index = np.where(visible, best, -1)

    stations = []
    for station in cfg.stations():
        lat = np.radians(float(station.latitude_deg))
        lon = np.radians(float(station.longitude_deg))
        radius = R_EARTH + float(station.altitude_m)
        stations.append({
            "name": str(station.name),
            # Earth-fixed, in km. The page turns these into inertial with the
            # planet rotation carried per frame, which is the same DCM the
            # access calculation used.
            "p": [round(float(v) / 1e3, 1) for v in (radius * np.array([
                np.cos(lat) * np.cos(lon),
                np.cos(lat) * np.sin(lon),
                np.sin(lat)]))],
        })

    orbits = []
    picks = []
    for start, stop, t_ref in segments:
        minutes = (env.t_s[start:stop] - t_ref) / 60.0
        local = _indices(minutes, grid)
        ok = local >= 0
        absolute = start + np.clip(local, 0, None)
        picks.append((ok, absolute))
        orbits.append({
            "ok": [int(v) for v in ok],
            "r": _flat(env.r_BN_N[absolute] / 1e3, 1),
            "sun": _flat(sun_hat[absolute], 4),
            "pn": _flat(env.dcm_PN[absolute], 5),
            "ecl": [int(v) for v in eclipse[absolute]],
            "st": [int(v) for v in station_index[absolute]],
        })

    attitude: dict[str, list] = {}
    for name, flown in timelines.items():
        frames = []
        for ok, absolute in picks:
            dcm = flown.dcm_BN[absolute]
            frames.append({
                "bx": _flat(dcm[:, 0, :], 4),
                "by": _flat(dcm[:, 1, :], 4),
                "bz": _flat(dcm[:, 2, :], 4),
            })
        attitude[name] = frames

    return {
        "points": VIZ_POINTS,
        "r_earth_km": round(R_EARTH / 1e3, 1),
        "grid": [round(float(v), 3) for v in grid],
        "stations": stations,
        "orbits": orbits,
        "attitude": attitude,
        "found_fov_deg": float(cfg.spacecraft.sensors.found_camera.fov_full_deg),
    }


STYLE = r"""
.globe{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:14px}
@media (max-width:820px){.globe{grid-template-columns:1fr}}
#scene{width:100%;aspect-ratio:4/3;display:block;border-radius:8px;
  background:var(--plane);cursor:grab;touch-action:none}
#scene:active{cursor:grabbing}
.vbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0 2px}
.vbar select,.vbar button{border:1px solid var(--axis);background:var(--panel);
  color:var(--ink);border-radius:6px;font:inherit;font-size:12px;padding:4px 8px;
  cursor:pointer}
.vbar button:hover{border-color:var(--accent);color:var(--accent)}
.vlegend{font-size:11px;color:var(--ink2);display:flex;flex-direction:column;
  gap:4px}
.vlegend span{display:inline-flex;align-items:center;gap:6px}
.vstat{font-size:12px;color:var(--ink2);font-variant-numeric:tabular-nums;
  display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin-top:8px}
.vstat b{font-weight:600;color:var(--ink)}
"""

MARKUP = r"""
<div class="card">
  <h2>Flight view</h2>
  <div class="note">The Vizard scene, drawn in the page: Earth turning under
  the orbit, the terminator, the Leaf Space sites, and the vehicle flying the
  attitude the scheduler chose. Drag to orbit the camera, scroll to zoom.</div>
  <div class="globe">
    <div>
      <canvas id="scene"></canvas>
      <div class="vbar">
        <button id="play">&#9654; Play</button>
        <select id="speed">
          <option value="1">1&times;</option>
          <option value="2" selected>2&times;</option>
          <option value="4">4&times;</option>
          <option value="8">8&times;</option>
        </select>
        <button id="vreset">Reset view</button>
        <span class="ocount" id="vtime"></span>
      </div>
    </div>
    <div>
      <div class="vlegend">
        <span><i class="swl" style="border-color:#d03b3b"></i><b>+x</b>&nbsp;FOUND
          boresight &mdash; the Earth limb it is imaging</span>
        <span><i class="swl" style="border-color:#2a78d6"></i><b>+z</b>&nbsp;LOST
          and star tracker boresight</span>
        <span><i class="swl" style="border-color:#1baf7a"></i><b>+y</b>&nbsp;completes
          the triad</span>
        <span><i class="sw" style="background:#eb6834"></i>ground station in
          view, with the link drawn</span>
        <span><i class="sw" style="background:#898781"></i>site below the
          horizon</span>
        <span><i class="swl" style="border-color:#898781;border-top-style:dashed"></i>orbit
          behind the Earth</span>
      </div>
      <div class="vstat" id="vstat"></div>
    </div>
  </div>
</div>
"""

SCRIPT = r"""
/* ------------------------------------------------------- flight view ----- */
const V = DATA.viz;
const cv = document.getElementById("scene"), ctx = cv.getContext("2d");
let cam = null, playing = false, vframe = 0;
let dragging = null;

const AXIS_COLORS = {bx: "#d03b3b", by: "#1baf7a", bz: "#2a78d6"};

function vdot(a, b){ return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }
function vcross(a, b){
  return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
}
function vnorm(a){
  const n = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0]/n, a[1]/n, a[2]/n];
}
function triple(list, i){ return [list[3*i], list[3*i+1], list[3*i+2]]; }

/* Orthographic camera looking at the origin. Orthographic rather than
   perspective on purpose: it keeps the orbit a true ellipse on screen, so
   what the eye measures off the picture is what the simulation computed. */
/* A default viewpoint tilted off the orbit normal, so the orbit reads as a
   wide ellipse rather than the edge-on sliver an arbitrary camera gives. From
   415 km the orbit is only 1.07 Earth radii, so the two are nearly the same
   circle and the viewing angle is most of what makes the picture legible. */
function defaultCam(){
  const o = V.orbits[orbit - 1] || V.orbits[0];
  const P = V.points;
  let a = null, b = null;
  for (let i = 0; i < P; i++) if (o.ok[i]){
    if (!a) a = triple(o.r, i);
    else if (!b && Math.abs(vdot(vnorm(a), vnorm(triple(o.r, i)))) < 0.6)
      b = triple(o.r, i);
  }
  if (!a || !b) return {yaw: 0.9, pitch: 0.45, zoom: 1};
  const h = vnorm(vcross(a, b));                 // orbit normal
  const inPlane = vnorm(vcross(h, a));
  const t = 0.62;                                // ~35 deg off the normal
  const eye = vnorm([h[0]*Math.cos(t) + inPlane[0]*Math.sin(t),
                     h[1]*Math.cos(t) + inPlane[1]*Math.sin(t),
                     h[2]*Math.cos(t) + inPlane[2]*Math.sin(t)]);
  return {yaw: Math.atan2(eye[1], eye[0]),
          pitch: Math.asin(Math.max(-1, Math.min(1, eye[2]))), zoom: 1};
}

function basis(){
  const cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
  const eye = [cp*Math.cos(cam.yaw), cp*Math.sin(cam.yaw), sp];
  let right = vcross([0,0,1], eye);
  if (Math.hypot(right[0], right[1], right[2]) < 1e-6) right = [1,0,0];
  right = vnorm(right);
  return {eye, right, up: vcross(eye, right)};
}

function sceneSize(){
  const rect = cv.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(rect.width*dpr) ||
      cv.height !== Math.round(rect.height*dpr)){
    cv.width = Math.round(rect.width*dpr);
    cv.height = Math.round(rect.height*dpr);
  }
  return {w: rect.width, h: rect.height, dpr};
}

function renderGlobe(){
  const o = V.orbits[orbit - 1];
  if (!o) return;
  const att = V.attitude[geo][orbit - 1];
  const P = V.points, Re = V.r_earth_km;
  const {w, h, dpr} = sceneSize();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  if (!cam) cam = defaultCam();
  const cx = w/2, cy = h/2;
  // Fit the orbit with headroom: the Sun marker and the FOUND ray both live
  // outside it, and at this altitude the orbit is barely clear of the globe.
  let rmax = Re;
  for (let i = 0; i < P; i++) if (o.ok[i])
    rmax = Math.max(rmax, Math.hypot(...triple(o.r, i)));
  const scale = (Math.min(w, h) * 0.44 / (rmax * 1.30)) * cam.zoom;
  const B = basis();
  const px = p => [cx + vdot(p, B.right)*scale, cy - vdot(p, B.up)*scale];
  const depth = p => vdot(p, B.eye);
  // Behind the globe from this viewpoint?
  const hidden = p => {
    if (depth(p) >= 0) return false;
    const sx = vdot(p, B.right), sy = vdot(p, B.up);
    return Math.hypot(sx, sy) < Re;
  };

  let f = Math.min(P - 1, Math.max(0, vframe));
  while (f > 0 && !o.ok[f]) f--;
  const sun = vnorm(triple(o.sun, f));
  const pn = o.pn.slice(9*f, 9*f + 9);
  // inertial = dcm_PN^T . fixed
  const toInertial = p => [
    pn[0]*p[0] + pn[3]*p[1] + pn[6]*p[2],
    pn[1]*p[0] + pn[4]*p[1] + pn[7]*p[2],
    pn[2]*p[0] + pn[5]*p[1] + pn[8]*p[2]];

  const live = o.st[f];
  const muted = css("--muted");

  /* -- orbit track behind the Earth ------------------------------------- */
  const drawTrack = wantHidden => {
    ctx.beginPath();
    let pen = false;
    for (let i = 0; i < P; i++){
      if (!o.ok[i]){ pen = false; continue; }
      const p = triple(o.r, i);
      if (hidden(p) !== wantHidden){ pen = false; continue; }
      const [x, y] = px(p);
      pen ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      pen = true;
    }
    ctx.strokeStyle = wantHidden ? muted : css("--accent");
    ctx.globalAlpha = wantHidden ? .45 : .9;
    ctx.lineWidth = wantHidden ? 1 : 1.6;
    ctx.setLineDash(wantHidden ? [3, 3] : []);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  };
  /* The vehicle and the Sun marker are drawn either side of the Earth
     depending on which side of it they are on, so the globe occludes them
     when it should. Nothing else here needs sorting: the graticule and the
     stations are tested face by face, and the track is split into a hidden
     pass and a visible one. */
  const scBehind = o.ok[f] && depth(triple(o.r, f)) < 0;
  const sunBehind = vdot(sun, B.eye) < 0;

  const drawSpacecraft = () => {
    const r = triple(o.r, f);
    const [sx, sy] = px(r);

    if (live >= 0){
      const st = toInertial(V.stations[live].p);
      const [lx, ly] = px(st);
      ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(lx, ly);
      ctx.strokeStyle = "#eb6834"; ctx.globalAlpha = .8; ctx.lineWidth = 1.2;
      ctx.setLineDash([4, 3]); ctx.stroke();
      ctx.setLineDash([]); ctx.globalAlpha = 1;
    }

    // FOUND's line of sight, out to where it crosses the Earth if it does.
    const bx = vnorm(triple(att.bx, f));
    const along = -vdot(r, bx);
    const disc = vdot(r, r) - along*along;
    const hitR = Math.sqrt(Math.max(0, Re*Re - disc));
    const reach = (disc <= Re*Re && along > 0) ? along - hitR : rmax*0.55;
    const tip = [r[0] + bx[0]*reach, r[1] + bx[1]*reach, r[2] + bx[2]*reach];
    const [tx, ty] = px(tip);
    ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(tx, ty);
    ctx.strokeStyle = "#d03b3b"; ctx.globalAlpha = .5; ctx.lineWidth = 1;
    ctx.stroke(); ctx.globalAlpha = 1;

    // Body triad, at a fixed screen length so it stays readable at any zoom.
    const arm = Math.min(w, h) * 0.10;
    for (const key of ["bx", "by", "bz"]){
      const v = vnorm(triple(att[key], f));
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(sx + vdot(v, B.right)*arm, sy - vdot(v, B.up)*arm);
      ctx.strokeStyle = AXIS_COLORS[key];
      ctx.lineWidth = 2.4;
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(sx, sy, 4, 0, 2*Math.PI);
    ctx.fillStyle = o.ecl[f] ? "#4a4a46" : "#f7f6f0";
    ctx.strokeStyle = "#0b0b0b"; ctx.lineWidth = 1.2;
    ctx.fill(); ctx.stroke();
  };

  const drawSun = () => {
    // A marker alone is ambiguous under an orthographic projection: with the
    // Sun near the view axis it lands on the disc and reads as a point on the
    // ground. The stalk from the Earth's centre makes it a direction, and the
    // label says which way it is going when the stalk foreshortens to nothing.
    const d = rmax * 1.26;
    const tip = [sun[0]*d, sun[1]*d, sun[2]*d];
    const [ux, uy] = px(tip);
    const [ox, oy] = px([0, 0, 0]);
    ctx.beginPath(); ctx.moveTo(ox, oy); ctx.lineTo(ux, uy);
    ctx.strokeStyle = "#e8b53a"; ctx.globalAlpha = .5; ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]); ctx.stroke();
    ctx.setLineDash([]); ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.arc(ux, uy, 5, 0, 2*Math.PI);
    ctx.fillStyle = "#e8b53a"; ctx.fill();
    const along = vdot(sun, B.eye);
    const label = Math.abs(along) > 0.9
      ? (along > 0 ? "Sun (toward you)" : "Sun (behind)") : "Sun";
    ctx.fillStyle = muted; ctx.font = "11px system-ui,sans-serif";
    ctx.fillText(label, ux + 8, uy + 3);
  };

  drawTrack(true);
  if (scBehind) drawSpacecraft();
  if (sunBehind) drawSun();

  /* -- Earth, lit from the real Sun direction --------------------------- */
  const sunScreenX = cx + vdot(sun, B.right)*Re*scale;
  const sunScreenY = cy - vdot(sun, B.up)*Re*scale;
  // Lit from wherever the Sun actually is. The highlight sits at the sub-solar
  // point and falls off across roughly one Earth radius, which puts the
  // terminator about where it belongs; with the Sun behind the globe the
  // highlight is off the disc entirely and the whole face reads as night.
  const facing = vdot(sun, B.eye) > 0;
  const g = ctx.createRadialGradient(
    sunScreenX, sunScreenY, Re*scale*0.15, sunScreenX, sunScreenY, Re*scale*1.85);
  g.addColorStop(0, facing ? "#8fb2d6" : "#44607b");
  g.addColorStop(0.35, "#5b7fa4");
  g.addColorStop(0.62, "#37516c");
  g.addColorStop(0.85, "#1e2f41");
  g.addColorStop(1, "#0e1822");
  ctx.beginPath();
  ctx.arc(cx, cy, Re*scale, 0, 2*Math.PI);
  ctx.fillStyle = g;
  ctx.fill();

  /* Graticule, so the rotation of the Earth under the orbit is visible. */
  ctx.strokeStyle = "rgba(255,255,255,.13)";
  ctx.lineWidth = 1;
  const grat = (fixedPoint, steps) => {
    ctx.beginPath();
    let pen = false;
    for (let s = 0; s <= steps; s++){
      const p = toInertial(fixedPoint(s / steps));
      if (depth(p) < 0){ pen = false; continue; }
      const [x, y] = px(p);
      pen ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      pen = true;
    }
    ctx.stroke();
  };
  for (let lat = -60; lat <= 60; lat += 30)
    grat(t => { const a = lat*Math.PI/180, b = t*2*Math.PI;
      return [Re*Math.cos(a)*Math.cos(b), Re*Math.cos(a)*Math.sin(b),
              Re*Math.sin(a)]; }, 64);
  for (let lon = 0; lon < 360; lon += 30)
    grat(t => { const b = lon*Math.PI/180, a = (t - .5)*Math.PI;
      return [Re*Math.cos(a)*Math.cos(b), Re*Math.cos(a)*Math.sin(b),
              Re*Math.sin(a)]; }, 48);

  /* -- ground stations --------------------------------------------------- */
  V.stations.forEach((s, k) => {
    const p = toInertial(s.p);
    if (depth(p) < 0) return;
    const [x, y] = px(p);
    ctx.beginPath();
    ctx.arc(x, y, k === live ? 4 : 2.4, 0, 2*Math.PI);
    ctx.fillStyle = k === live ? "#eb6834" : "rgba(220,220,215,.55)";
    ctx.fill();
    if (k === live){
      ctx.fillStyle = css("--ink");
      ctx.font = "11px system-ui,sans-serif";
      ctx.fillText(s.name, x + 7, y + 3);
    }
  });

  drawTrack(false);
  if (o.ok[f] && !scBehind) drawSpacecraft();
  if (!sunBehind) drawSun();

  renderVStat(o, att, f);
}

function renderVStat(o, att, f){
  const modes = ["safe","standby","slew","experiment","downlink"];
  const chart = G[geo].orbits[orbit - 1];
  const j = Math.round(f * (M.grid.length - 1) / (V.points - 1));
  const live = o.st[f];
  const rows = [
    ["frame", `t + ${V.grid[f].toFixed(1)} min`],
    ["mode", chart.mode[j] === null ? "—" : modes[chart.mode[j]]],
    ["altitude", (Math.hypot(...triple(o.r, f)) - V.r_earth_km).toFixed(0) + " km"],
    ["sunlight", o.ecl[f] ? "eclipse" : "sunlit"],
    ["station", live >= 0 ? V.stations[live].name : "none in view"],
    ["SOC", chart.soc[j] === null ? "—" : chart.soc[j].toFixed(1) + " %"],
  ];
  document.getElementById("vstat").innerHTML = rows.map(([k, v]) =>
    `<span>${k}</span><b>${v}</b>`).join("");
  document.getElementById("vtime").textContent =
    `frame ${f + 1} / ${V.points}`;
}

/* Chart hover drives the scene, so the cursor and the picture agree. */
function globeFollowCursor(i){
  vframe = Math.round(i * (V.points - 1) / (M.grid.length - 1));
  renderGlobe();
}

let raf = null, last = 0;
function tick(now){
  if (!playing) return;
  const rate = +document.getElementById("speed").value;
  if (now - last > 90 / rate){
    last = now;
    vframe++;
    if (vframe >= V.points){
      vframe = 0;
      if (orbit < G[geo].orbits.length) { setOrbit(orbit + 1); }
      else { setPlaying(false); }
    }
    renderGlobe();
  }
  raf = requestAnimationFrame(tick);
}

function setPlaying(on){
  playing = on;
  document.getElementById("play").innerHTML = on ? "&#10073;&#10073; Pause"
                                                 : "&#9654; Play";
  if (on){ last = 0; raf = requestAnimationFrame(tick); }
  else if (raf){ cancelAnimationFrame(raf); raf = null; }
}

document.getElementById("play").onclick = () => setPlaying(!playing);
document.getElementById("vreset").onclick = () => {
  cam = defaultCam(); renderGlobe();
};
cv.addEventListener("pointerdown", e => {
  dragging = {x: e.clientX, y: e.clientY, ...cam};
  cv.setPointerCapture(e.pointerId);
});
cv.addEventListener("pointermove", e => {
  if (!dragging) return;
  cam.yaw = dragging.yaw - (e.clientX - dragging.x) * 0.008;
  cam.pitch = Math.max(-1.45, Math.min(1.45,
    dragging.pitch + (e.clientY - dragging.y) * 0.008));
  renderGlobe();
});
const endDrag = () => { dragging = null; };
cv.addEventListener("pointerup", endDrag);
cv.addEventListener("pointercancel", endDrag);
cv.addEventListener("wheel", e => {
  e.preventDefault();
  cam.zoom = Math.max(0.5, Math.min(4, cam.zoom * (e.deltaY > 0 ? 0.9 : 1.1)));
  renderGlobe();
}, {passive: false});
addEventListener("resize", () => renderGlobe());
"""
