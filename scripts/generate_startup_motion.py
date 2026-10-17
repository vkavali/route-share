#!/usr/bin/env python3
"""Extract approved SeatPal landing artwork and generate shared startup motion assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app/templates/_seatpal-landing-brand.html"
SOURCE_LABEL = "app/templates/_seatpal-landing-brand.html"
FULL = ("120 130 740 310", 120, 130, 740, 310)
SEAT = ("-150 -180 300 360", -150, -180, 300, 360)
WHEEL = ("-60 -60 120 120", -60, -60, 120, 120)

ENGINE = r'''// Generated from the approved SeatPal landing motion. Pure frame calculation; no DOM or timing side effects.
export const STARTUP_MS = 3600;
export const STARTUP_ASSET_HASH = '__STARTUP_ASSET_HASH__';
export const VIEW_BOX = Object.freeze({ x: 120, y: 130, width: 740, height: 310 });
const LOGO_VIEW_BOX = Object.freeze({ x: 285, y: 183, width: 430, height: 430 * 310 / 740 });
const clamp = (x) => Math.min(1, Math.max(0, x));
const ease = (x) => { x = clamp(x); return x * x * x * (x * (x * 6 - 15) + 10); };
const phase = (t, a, b) => ease((t - a) / (b - a));
const mix = (a, b, p) => a + (b - a) * p;

export function frameAt(progress) {
  const p = clamp(Number(progress) || 0);
  const intoCar = phase(p, .08, .28), toBike = phase(p, .38, .61), resolve = phase(p, .69, .89);
  const openingCamera = phase(p, .08, .28);
  const carBuild = phase(p, .12, .29), carLineRetract = phase(p, .36, .48);
  const carFillBuild = phase(p, .22, .32), carFillRetract = phase(p, .36, .43);
  const bikeBuild = phase(p, .48, .64), bikeRetract = phase(p, .73, .91);
  const bikeFillBuild = phase(p, .55, .64);
  let seatX = mix(466, 328, intoCar), seatY = mix(307, 326, intoCar), seatScale = mix(1.1, .76, intoCar);
  seatX = mix(seatX, 410, toBike); seatY = mix(seatY, 282, toBike); seatScale = mix(seatScale, .52, toBike);
  seatX = mix(seatX, 315, resolve); seatY = mix(seatY, 306, resolve); seatScale = mix(seatScale, .54, resolve);
  const fold = toBike * (1 - resolve);
  const backBase = mix(mix(-8, -12, intoCar), -8, resolve);
  const backAngle = mix(backBase, -88, fold);
  const backScaleX = mix(1, .55, fold);
  const carLineProgress = carBuild * (1 - carLineRetract);
  const carFillOpacity = carFillBuild * (1 - carFillRetract);
  const driverOpacity = phase(p, .24, .32) * (1 - phase(p, .36, .45));
  const carOpacity = carLineProgress;
  const bikeLineProgress = bikeBuild * (1 - bikeRetract);
  const bikeFillOpacity = bikeFillBuild * (1 - bikeRetract);
  const bikeOpacity = bikeLineProgress;
  const bikeDecorationOpacity = bikeBuild * (1 - bikeRetract);
  const bikeRearDetailsOpacity = bikeBuild * (1 - bikeRetract);
  const tankOpacity = bikeFillBuild * (1 - phase(p, .69, .77));
  const engineOpacity = bikeFillBuild * (1 - phase(p, .69, .77));
  const wheelTransfer = phase(p, .44, .61);
  let rearX = mix(260, 365, wheelTransfer), frontX = mix(700, 585, wheelTransfer);
  const rearStart = rearX, frontStart = frontX;
  const collect = phase(p, .70, .89), targetX = seatX, targetY = seatY + 3 * seatScale;
  const bikeLift = 22 * Math.sin(Math.PI * collect), bikeKeep = 1 - collect;
  rearX = mix(rearX, targetX, collect); frontX = mix(frontX, targetX, collect);
  const wheelY = mix(365, targetY, collect) + bikeLift;
  const wheelScale = Math.pow(1 - collect, 1.4) + .035 * collect;
  const words = phase(p, .79, .95);
  const camera = phase(p, .80, .96);
  const viewWidth = mix(VIEW_BOX.width, LOGO_VIEW_BOX.width, camera);
  const view = {
    viewBoxX: mix(mix(127, VIEW_BOX.x, openingCamera), LOGO_VIEW_BOX.x, camera),
    viewBoxY: mix(mix(88, VIEW_BOX.y, openingCamera), LOGO_VIEW_BOX.y, camera),
    viewBoxWidth: viewWidth,
    viewBoxHeight: viewWidth * VIEW_BOX.height / VIEW_BOX.width,
  };
  return {
    seatX, seatY, seatScale, backAngle, backScaleX,
    railOpacity: 1 - fold,
    carOpacity, carLineProgress, carFillOpacity, carDecorationOpacity: carFillOpacity,
    carSmallDetailsOpacity: carFillOpacity, driverOpacity, carX: 0, carScaleX: 1,
    bikeOpacity, bikeLineProgress, bikeFillOpacity, bikeDecorationOpacity, bikeRearDetailsOpacity, tankOpacity, engineOpacity,
    bikeX: targetX * collect, bikeY: targetY * collect + bikeLift, bikeScale: bikeKeep,
    rearX, frontX, wheelY, wheelScale,
    wheelOpacity: 1 - phase(p, .89, .94),
    rearRotation: (rearX - 260) / 52.5 * 180 / Math.PI,
    frontRotation: (frontX - 700) / 52.5 * 180 / Math.PI,
    wordOpacity: words, wordReveal: words, wordX: 10 * (1 - words), ...view,
  };
}
'''

DECLARATION = '''export type StartupFrame = {
  seatX: number; seatY: number; seatScale: number; backAngle: number; backScaleX: number;
  railOpacity: number; carOpacity: number; carLineProgress: number; carFillOpacity: number;
  carDecorationOpacity: number; carSmallDetailsOpacity: number; driverOpacity: number; carX: number; carScaleX: number;
  bikeOpacity: number; bikeLineProgress: number; bikeFillOpacity: number; bikeDecorationOpacity: number;
  bikeRearDetailsOpacity: number; tankOpacity: number; engineOpacity: number; bikeX: number; bikeY: number; bikeScale: number;
  rearX: number; frontX: number; wheelY: number; wheelScale: number; wheelOpacity: number;
  rearRotation: number; frontRotation: number; wordOpacity: number; wordReveal: number; wordX: number;
  viewBoxX: number; viewBoxY: number; viewBoxWidth: number; viewBoxHeight: number;
};
export declare const STARTUP_MS: 3600;
export declare const STARTUP_ASSET_HASH: string;
export declare const VIEW_BOX: Readonly<{ x: 120; y: 130; width: 740; height: 310 }>;
export declare function frameAt(progress: number): StartupFrame;
export declare const STARTUP_FRAME0_SVG: string;
'''


def _tag(element: ET.Element, name: str) -> bool:
    return element.tag.rsplit("}", 1)[-1] == name


def _find(root: ET.Element, element_id: str) -> ET.Element:
    for el in root.iter():
        if el.get("id") == element_id:
            return el
    raise ValueError(f"SVG element not found: {element_id}")


def _sanitize(element: ET.Element) -> None:
    for el in element.iter():
        classes = set(el.get("class", "").split())
        if "ink" in classes:
            el.set("stroke", "#34414b")
            el.set("fill", "none")
            el.set("stroke-linecap", "round")
            el.set("stroke-linejoin", "round")
        if el.get("opacity") == "0":
            el.attrib.pop("opacity")


def _svg_part(view: tuple[str, int, int, int, int], child: ET.Element, *, remove_transform: bool = False) -> dict:
    box, x, y, width, height = view
    root = ET.Element("svg", {"xmlns": "http://www.w3.org/2000/svg", "viewBox": box})
    clone = ET.fromstring(ET.tostring(child, encoding="unicode"))
    if remove_transform:
        clone.attrib.pop("transform", None)
    _sanitize(clone)
    root.append(clone)
    return {"xml": ET.tostring(root, encoding="unicode", short_empty_elements=True), "viewBox": box, "x": x, "y": y, "width": width, "height": height}


def _children_only(parent: ET.Element, *, omit_ids: set[str] | None = None) -> ET.Element:
    omit_ids = omit_ids or set()
    group = ET.Element("g")
    for child in list(parent):
        if child.get("id") not in omit_ids:
            group.append(ET.fromstring(ET.tostring(child, encoding="unicode")))
    return group


def _clone(element: ET.Element) -> ET.Element:
    clone = ET.fromstring(ET.tostring(element, encoding="unicode"))
    _sanitize(clone)
    return clone


def _remove_trace_paths(element: ET.Element, trace_class: str) -> ET.Element:
    clone = _clone(element)
    for parent in list(clone.iter()):
        for child in list(parent):
            if trace_class in child.get("class", "").split():
                parent.remove(child)
    return clone


def _trace_metadata(element: ET.Element, trace_class: str) -> list[dict]:
    traces = []
    for path in element.iter():
        if not _tag(path, "path") or trace_class not in path.get("class", "").split():
            continue
        clone = _clone(path)
        traces.append({
            "id": clone.get("id"), "className": clone.get("class", ""), "d": clone.get("d", ""),
            "fill": clone.get("fill", "none"), "stroke": clone.get("stroke", "#34414b"),
            "strokeWidth": clone.get("stroke-width", "2"),
            "strokeLinecap": clone.get("stroke-linecap", "round"),
            "strokeLinejoin": clone.get("stroke-linejoin", "round"),
        })
    return traces


def _append_part(root: ET.Element, part: dict, group: ET.Element, transform: str = "") -> None:
    if transform:
        group.set("transform", transform)
    source = ET.fromstring(part["xml"])
    for child in list(source):
        group.append(ET.fromstring(ET.tostring(child, encoding="unicode")))
    root.append(group)


def _frame0_svg(parts: dict) -> str:
    svg = ET.Element("svg", {
        "xmlns": "http://www.w3.org/2000/svg", "viewBox": "127 88 740 310",
        "width": "100%", "height": "100%", "focusable": "false", "aria-hidden": "true",
        "data-seatpal-frame": "0",
    })
    seat = ET.Element("g", {"transform": "translate(466 307) scale(1.1)"})
    _append_part(svg, parts["seatBack"], ET.Element("g", {"transform": "rotate(-8)"}))
    # Reparent the just-added back group into its seat assembly, then append rail and base.
    back = svg[-1]
    svg.remove(back)
    seat.append(back)
    _append_part(seat, parts["seatRail"], ET.Element("g"))
    _append_part(seat, parts["seatBase"], ET.Element("g"))
    svg.append(seat)
    return ET.tostring(svg, encoding="unicode", short_empty_elements=True)


def _replace_fallback_marker(markup: bytes, fallback: str) -> bytes:
    # The generated SVG is LF-terminated; normalize the enclosing static preview too.
    markup = markup.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    start = b"<!-- seatpal:startup-frame0:start -->"
    end = b"<!-- seatpal:startup-frame0:end -->"
    if markup.count(start) != 1 or markup.count(end) != 1:
        raise ValueError("Preview must contain exactly one startup frame-zero marker pair")
    left, remainder = markup.split(start, 1)
    _, right = remainder.split(end, 1)
    replacement = b"\n          " + fallback.encode() + b"\n          "
    return left + start + replacement + end + right


def generate() -> dict[str, bytes]:
    raw = SOURCE.read_bytes()
    match = re.search(rb"<svg\b.*?</svg>", raw, flags=re.DOTALL)
    if not match:
        raise ValueError("Could not find standalone SVG in approved landing template")
    svg = ET.fromstring(match.group(0))
    car = _find(svg, "sp-seatpal-car")
    bike = _find(svg, "sp-seatpal-bike")
    rear = _find(svg, "sp-seatpal-rear-wheel")
    front = _find(svg, "sp-seatpal-front-wheel")
    seat = _find(svg, "sp-seatpal-seat")
    back = _find(svg, "sp-seatpal-seat-back")
    rail = _find(svg, "sp-seatpal-seat-rail")
    word = _find(svg, "sp-seatpal-wordmark")
    wordmark = _clone(word)
    wordmark.attrib.pop("clip-path", None)
    text = next(el for el in wordmark.iter() if _tag(el, "text"))
    text.attrib.pop("style", None)
    text.set("font-size", "86px")
    text.set("font-weight", "700")
    text.set("font-family", "Manrope, Segoe UI, sans-serif")
    text.set("letter-spacing", "-4px")
    # Assemble native-ready body/detail layers from the exact approved source nodes.
    car_decoration = _find(car, "sp-seatpal-car-decoration")
    car_small_details = _find(car, "sp-seatpal-car-small-details")
    driver_seat = _find(car, "sp-seatpal-driver-seat")
    bike_decoration = _find(bike, "sp-seatpal-bike-decoration")
    bike_engine = _find(bike, "sp-seatpal-bike-engine")
    bike_rear_details = _find(bike, "sp-seatpal-bike-rear-details")
    tank_fill = _find(bike, "sp-seatpal-tank-fill")
    bike_base_fills = ET.Element("g", {"id": "sp-seatpal-bike-body-fills"})
    for path in bike.iter():
        if not _tag(path, "path") or "bike-fill" not in path.get("class", "").split() or path is tank_fill:
            continue
        ancestors = [parent for parent in bike.iter() if path in list(parent)]
        # Decoration has its own opacity phase, so do not flatten its fill into the bike body.
        if any(parent.get("id") == "sp-seatpal-bike-decoration" for parent in ancestors):
            continue
        bike_base_fills.append(_clone(path))
    parts = {
        "car": _svg_part(FULL, car),
        "bike": _svg_part(FULL, bike),
        "carBody": _svg_part(FULL, _find(car, "sp-seatpal-car-fill")),
        "carDecoration": _svg_part(FULL, car_decoration),
        "carSmallDetails": _svg_part(FULL, car_small_details),
        "driverSeat": _svg_part(FULL, driver_seat),
        "carTracePaths": _trace_metadata(car, "car-trace"),
        "bikeBody": _svg_part(FULL, bike_base_fills),
        "bikeDecoration": _svg_part(FULL, bike_decoration),
        "tankFill": _svg_part(FULL, tank_fill),
        "bikeEngine": _svg_part(FULL, bike_engine),
        "bikeRearDetails": _svg_part(FULL, bike_rear_details),
        "bikeTracePaths": _trace_metadata(bike, "bike-trace"),
        "rearWheel": _svg_part(WHEEL, rear),
        "frontWheel": _svg_part(WHEEL, front),
        "seatBack": _svg_part(SEAT, back, remove_transform=True),
        "seatRail": _svg_part(SEAT, rail),
        "seatBase": _svg_part(SEAT, _children_only(seat, omit_ids={"sp-seatpal-seat-rail", "sp-seatpal-seat-back"})),
        "wordmark": _svg_part(FULL, wordmark),
    }
    # The seat base includes its cushion, stitch and hinge; retain only those remaining children.
    source = {"path": SOURCE_LABEL, "sha256": hashlib.sha256(raw).hexdigest()}
    data = {"version": 2, "source": source, "parts": parts,
            "wordmarkClip": {"x": 385, "y": 215, "width": 400, "height": 130}}
    json_bytes = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    fallback = _frame0_svg(parts)
    asset_hash = hashlib.sha256(json_bytes).hexdigest()
    engine = ENGINE.replace("__STARTUP_ASSET_HASH__", asset_hash)
    js_bytes = (engine + "\nexport const STARTUP_FRAME0_SVG = " + json.dumps(fallback, ensure_ascii=True) + ";\n").encode()
    preview_path = ROOT / "static/seatpal-startup-preview.html"
    preview_bytes = _replace_fallback_marker(preview_path.read_bytes(), fallback)
    return {
        "static/assets/seatpal/startup-motion.json": json_bytes,
        "mobile/assets/seatpal/startup-motion.json": json_bytes,
        "static/seatpal-startup-motion.js": js_bytes,
        "mobile/src/generated/seatpal-startup-motion.js": js_bytes,
        "mobile/src/generated/seatpal-startup-motion.d.ts": DECLARATION.encode(),
        "static/seatpal-startup-preview.html": preview_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify generated outputs are current without writing")
    args = parser.parse_args()
    outputs = generate()
    stale = []
    for relative, content in outputs.items():
        path = ROOT / relative
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                stale.append(relative)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    if stale:
        print("Stale generated startup motion files: " + ", ".join(stale), file=sys.stderr)
        return 1
    print("Startup motion outputs " + ("are current" if args.check else "generated") + f" ({len(outputs)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
