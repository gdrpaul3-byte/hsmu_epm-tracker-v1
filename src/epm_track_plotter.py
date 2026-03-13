import argparse
import csv
import os
from typing import List, Tuple, Dict, Optional

import cv2
import numpy as np

Point = Tuple[int, int]


def load_zones(path: Optional[str]) -> List[Dict]:
    if not path or not os.path.isfile(path):
        return []
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("zones", []) or []


def load_roi(path: Optional[str]) -> List[Point]:
    if not path or not os.path.isfile(path):
        return []
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    pts = data.get("points", [])
    return [(int(p[0]), int(p[1])) for p in pts]


def read_track_csv(path: str) -> Tuple[List[Point], List[float]]:
    pts: List[Point] = []
    ts: List[float] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header: Optional[List[str]] = None
        for row in reader:
            if not row:
                continue
            if row[0].startswith("#"):
                continue
            header = row
            break
        if header is None:
            return pts, ts
        idx_x = header.index("x")
        idx_y = header.index("y")
        idx_t = header.index("timestamp_s") if "timestamp_s" in header else None
        for row in reader:
            try:
                pts.append((int(float(row[idx_x])), int(float(row[idx_y]))))
                if idx_t is not None:
                    ts.append(float(row[idx_t]))
            except Exception:
                continue
    if idx_t is None:
        ts = [float(i) for i in range(len(pts))]
    return pts, ts


def capture_reference_frame(video_path: str, frame_idx: int = 0) -> Optional[np.ndarray]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_idx))
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def point_in_zone(pt: Point, zones: List[Dict]) -> Optional[str]:
    x, y = pt
    for z in zones:
        poly = np.array(z.get("points", []), np.int32)
        if poly.size == 0:
            continue
        if cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0:
            return str(z.get("name", "zone"))
    return None


def aggregate_zones(totals: Dict[str, float]) -> List[Tuple[str, float]]:
    rem = dict(totals)
    agg: List[Tuple[str, float]] = []
    if "center" in rem:
        agg.append(("center", rem.pop("center")))
    open_sum = sum(val for name, val in list(rem.items()) if "open_arm" in name.lower())
    rem = {k: v for k, v in rem.items() if "open_arm" not in k.lower()}
    if open_sum > 0:
        agg.append(("open arms", open_sum))
    closed_sum = sum(val for name, val in list(rem.items()) if "closed_arm" in name.lower())
    rem = {k: v for k, v in rem.items() if "closed_arm" not in k.lower()}
    if closed_sum > 0:
        agg.append(("closed arms", closed_sum))
    for name in sorted(rem.keys()):
        agg.append((name, rem[name]))
    return agg


def main() -> None:
    parser = argparse.ArgumentParser(description="Render EPM track/heatmap from CSV")
    parser.add_argument("--csv", required=True, help="Track CSV produced by tracker")
    parser.add_argument("--video", required=True, help="Original video to grab background frame")
    parser.add_argument("--frame", type=int, default=0, help="Frame index for background snapshot")
    parser.add_argument("--roi", type=str, default=None, help="ROI JSON")
    parser.add_argument("--zones", type=str, default=None, help="Zones JSON")
    parser.add_argument("--output", type=str, default=None, help="Output prefix (default: csv basename)")
    args = parser.parse_args()

    pts, ts = read_track_csv(args.csv)
    if not pts:
        print("[WARN] CSV has no track points")
        return

    frame = capture_reference_frame(args.video, args.frame)
    if frame is None:
        raise RuntimeError("Failed to capture reference frame")

    roi_pts = load_roi(args.roi)
    zones = load_zones(args.zones)

    overlay = frame.copy()
    if roi_pts:
        cv2.polylines(overlay, [np.array(roi_pts, np.int32)], True, (0, 255, 255), 2)
    if zones:
        for z in zones:
            poly = np.array(z.get("points", []), np.int32)
            if poly.size == 0:
                continue
            cv2.polylines(overlay, [poly], True, (0, 0, 0), 3)
            cv2.polylines(overlay, [poly], True, (255, 255, 255), 1)
    for i in range(1, len(pts)):
        cv2.line(overlay, pts[i - 1], pts[i], (0, 0, 255), 3)

    heatmap = np.zeros(frame.shape[:2], dtype=np.float32)
    for (x, y) in pts:
        if 0 <= y < heatmap.shape[0] and 0 <= x < heatmap.shape[1]:
            heatmap[y, x] += 1
    if heatmap.max() > 0:
        ksize = max(5, (min(heatmap.shape[:2]) // 30) | 1)
        heatmap = cv2.GaussianBlur(heatmap, (ksize, ksize), 0)
        hm_norm = heatmap / max(heatmap.max(), 1.0)
        hm_color = cv2.applyColorMap((hm_norm * 255).astype(np.uint8), cv2.COLORMAP_HOT)
        mask = (hm_norm > 0).astype(np.uint8)[..., None]
        heat_overlay = frame.copy()
        heat_overlay = cv2.addWeighted(heat_overlay, 0.5, hm_color, 0.7, 0)
        heat_overlay = np.where(mask, heat_overlay, frame)
    else:
        heat_overlay = frame.copy()

    totals: Dict[str, float] = {}
    last_zone: Optional[str] = None
    last_ts: Optional[float] = None
    for idx, pt in enumerate(pts):
        zone = point_in_zone(pt, zones) if zones else None
        if zone is None and roi_pts:
            roi_poly = np.array(roi_pts, np.int32)
            if cv2.pointPolygonTest(roi_poly, (float(pt[0]), float(pt[1])), False) >= 0:
                zone = "center"
        current_ts = ts[idx] if idx < len(ts) else float(idx)
        if zone != last_zone:
            last_zone = zone
            last_ts = current_ts
        else:
            if last_zone is not None and last_ts is not None:
                totals[last_zone] = totals.get(last_zone, 0.0) + max(0.0, current_ts - last_ts)
                last_ts = current_ts
    agg = aggregate_zones(totals)
    if agg:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        labels = [name for name, _ in agg]
        values = [val for _, val in agg]
        total_sum = sum(values) or 1.0
        perc = [(val / total_sum) * 100.0 for val in values]
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
        ax1.bar(labels, values, color="#4e79a7"); ax1.set_title("Total time (s)"); ax1.set_ylabel("s")
        ax2.bar(labels, perc, color="#d37295"); ax2.set_title("Percentage (%)"); ax2.set_ylabel("%")
        for ax in (ax1, ax2):
            for tick in ax.get_xticklabels():
                tick.set_rotation(15)
        plt.tight_layout()
        prefix = args.output or os.path.splitext(args.csv)[0]
        fig.savefig(prefix + "_zone_stats.png", bbox_inches="tight")
        plt.close(fig)
    else:
        prefix = args.output or os.path.splitext(args.csv)[0]

    prefix = args.output or os.path.splitext(args.csv)[0]
    cv2.imwrite(prefix + "_track_plot.png", overlay)
    cv2.imwrite(prefix + "_heatmap.png", heat_overlay)


if __name__ == "__main__":
    main()
