#!/usr/bin/env python3
"""
Aggregate EPM zone stats (open vs closed arms), compute per-mouse occupancy,
run stats (paired t for open vs closed, independent t for sex on open_pct),
and save plots/CSVs with bilingual labels.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# Optional plotting
try:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt  # type: ignore
    from matplotlib import font_manager, rcParams  # type: ignore

    _HAS_MPL = True
except Exception:
    _HAS_MPL = False

# Optional pandas/statsmodels (for potential future ANOVA; not strictly required here)
try:
    import pandas as pd  # type: ignore

    _HAS_PD = True
except Exception:
    _HAS_PD = False


@dataclass
class ZoneRow:
    mouse_id: str
    video: str
    zone: str
    total_time_s: float


@dataclass
class MouseAgg:
    mouse_id: str
    video: str
    sex: Optional[str]
    open_time_s: float
    closed_time_s: float

    @property
    def total_time_s(self) -> float:
        return self.open_time_s + self.closed_time_s

    def pct_open(self) -> float:
        return (self.open_time_s / self.total_time_s * 100.0) if self.total_time_s > 0 else 0.0

    def pct_closed(self) -> float:
        return (self.closed_time_s / self.total_time_s * 100.0) if self.total_time_s > 0 else 0.0


def parse_zone_file(path: Path) -> Iterable[ZoneRow]:
    """Yield rows from a *_epm_track_zones.csv file."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                norm = {k.strip().lstrip("\ufeff").lower(): v for k, v in row.items() if k}
                zone_raw = norm.get("zone")
                total_raw = norm.get("total_time_s")
                if zone_raw is None or total_raw is None:
                    continue
                zone = str(zone_raw).strip().lower()
                total_time = float(total_raw)
                yield ZoneRow(
                    mouse_id=path.stem.split("_")[0].strip().upper(),
                    video=path.stem.replace("_track_zones", "") + ".mp4",
                    zone=zone,
                    total_time_s=total_time,
                )
            except Exception:
                continue


def infer_sex(mouse_id: str) -> Optional[str]:
    low = mouse_id.lower()
    if low.startswith("f"):
        return "F"
    if low.startswith("m"):
        return "M"
    return None


def setup_font(base: Path) -> None:
    if not _HAS_MPL:
        return
    candidates = [
        base / "NanumGothic.ttf",
        base / "NanumGothicBold.ttf",
        base / "NanumGothicExtraBold.ttf",
        base / "NanumGothicLight.ttf",
    ]
    for c in candidates:
        if c.exists():
            try:
                font_manager.fontManager.addfont(str(c))
                name = font_manager.FontProperties(fname=str(c)).get_name()
                rcParams["font.family"] = name
                rcParams["axes.unicode_minus"] = False
                break
            except Exception:
                continue


def aggregate_mice(data_dir: Path) -> List[MouseAgg]:
    mice: Dict[str, MouseAgg] = {}
    for zone_csv in sorted(data_dir.glob("*_epm_track_zones.csv")):
        for row in parse_zone_file(zone_csv):
            agg = mice.get(row.mouse_id)
            if agg is None:
                agg = MouseAgg(
                    mouse_id=row.mouse_id,
                    video=row.video,
                    sex=infer_sex(row.mouse_id),
                    open_time_s=0.0,
                    closed_time_s=0.0,
                )
                mice[row.mouse_id] = agg
            if "open_arm" in row.zone or row.zone == "open arms":
                agg.open_time_s += row.total_time_s
            elif "closed_arm" in row.zone or row.zone == "closed arms":
                agg.closed_time_s += row.total_time_s
    return list(mice.values())


def two_tailed_t_pvalue(t_stat: float, df: float) -> float:
    if df <= 0 or not math.isfinite(t_stat):
        return float("nan")
    x = df / (df + t_stat * t_stat)

    def _betacf(a: float, b: float, x: float) -> float:
        MAXIT = 200
        EPS = 3e-7
        FPMIN = 1e-30
        qab = a + b
        qap = a + 1.0
        qam = a - 1.0
        c = 1.0
        d = 1.0 - qab * x / qap
        if abs(d) < FPMIN:
            d = FPMIN
        d = 1.0 / d
        h = d
        for m in range(1, MAXIT + 1):
            m2 = 2 * m
            aa = m * (b - m) * x / ((qam + m2) * (a + m2))
            d = 1.0 + aa * d
            if abs(d) < FPMIN:
                d = FPMIN
            c = 1.0 + aa / c
            if abs(c) < FPMIN:
                c = FPMIN
            d = 1.0 / d
            h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
            d = 1.0 + aa * d
            if abs(d) < FPMIN:
                d = FPMIN
            c = 1.0 + aa / c
            if abs(c) < FPMIN:
                c = FPMIN
            d = 1.0 / d
            delh = d * c
            h *= delh
            if abs(delh - 1.0) < EPS:
                break
        return h

    def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        ln_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        front = math.exp(a * math.log(x) + b * math.log(1.0 - x) + ln_beta)
        if x < (a + 1.0) / (a + b + 2.0):
            return front * _betacf(a, b, x) / a
        return 1.0 - front * _betacf(b, a, 1.0 - x) / b

    ib = _regularized_incomplete_beta(df / 2.0, 0.5, x)
    cdf = 1.0 - 0.5 * ib if t_stat > 0 else 0.5 * ib
    return 2.0 * min(cdf, 1.0 - cdf)


def paired_t(open_vals: List[float], closed_vals: List[float]) -> Tuple[float, float, float]:
    diffs = [o - c for o, c in zip(open_vals, closed_vals)]
    if len(diffs) < 2:
        return float("nan"), float("nan"), float("nan")
    mean_diff = statistics.mean(diffs)
    sd_diff = statistics.stdev(diffs)
    se_diff = sd_diff / math.sqrt(len(diffs))
    t_stat = mean_diff / se_diff if se_diff > 0 else float("nan")
    p_val = two_tailed_t_pvalue(t_stat, len(diffs) - 1)
    return mean_diff, t_stat, p_val


def independent_t(vals_a: List[float], vals_b: List[float]) -> Tuple[float, float, float]:
    if len(vals_a) < 2 or len(vals_b) < 2:
        return float("nan"), float("nan"), float("nan")
    mean_a = statistics.mean(vals_a)
    mean_b = statistics.mean(vals_b)
    var_a = statistics.variance(vals_a)
    var_b = statistics.variance(vals_b)
    pooled = ((len(vals_a) - 1) * var_a + (len(vals_b) - 1) * var_b) / (len(vals_a) + len(vals_b) - 2)
    se = math.sqrt(pooled * (1.0 / len(vals_a) + 1.0 / len(vals_b))) if pooled > 0 else float("nan")
    t_stat = (mean_a - mean_b) / se if se and math.isfinite(se) else float("nan")
    df = len(vals_a) + len(vals_b) - 2
    p_val = two_tailed_t_pvalue(t_stat, df)
    return mean_a - mean_b, t_stat, p_val


def save_plot_all(mice: List[MouseAgg], out_dir: Path) -> None:
    if not _HAS_MPL:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = [m.mouse_id for m in mice]
    open_pct = [m.pct_open() for m in mice]
    closed_pct = [m.pct_closed() for m in mice]
    x = range(len(mice))
    width = 0.35
    fig, ax = plt.subplots(figsize=(max(6, len(mice) * 0.6), 5))
    ax.bar([i - width / 2 for i in x], closed_pct, width, label="closed arms / 닫힌 팔", color="#4e79a7")
    ax.bar([i + width / 2 for i in x], open_pct, width, label="open arms / 열린 팔", color="#d37295")
    for i, (o, c) in enumerate(zip(open_pct, closed_pct)):
        jitter = (i % 5) * 0.05
        ax.scatter(i - width / 2 + jitter, c, color="#4e79a7", edgecolors="k", zorder=3)
        ax.scatter(i + width / 2 + jitter, o, color="#d37295", edgecolors="k", zorder=3)
    ax.set_ylabel("Occupancy (%) / 점유율")
    ax.set_title("EPM occupancy by mouse (closed vs open) / 개체별 닫힌 vs 열린 팔 점유율")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=20)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "epm_open_closed_by_mouse.png", bbox_inches="tight")
    plt.close(fig)


def save_plot_sex(mice: List[MouseAgg], out_dir: Path, p_val: Optional[float] = None) -> None:
    if not _HAS_MPL:
        return
    groups = {"M": [m for m in mice if m.sex == "M"], "F": [m for m in mice if m.sex == "F"]}
    labels = []
    closed_means = []
    closed_sem = []
    open_means = []
    open_sem = []
    for sex, group in groups.items():
        if not group:
            continue
        labels.append(sex)
        closed_vals = [m.pct_closed() for m in group]
        open_vals = [m.pct_open() for m in group]
        closed_means.append(statistics.mean(closed_vals))
        open_means.append(statistics.mean(open_vals))
        closed_sem.append(statistics.stdev(closed_vals) / math.sqrt(len(closed_vals)) if len(closed_vals) > 1 else 0.0)
        open_sem.append(statistics.stdev(open_vals) / math.sqrt(len(open_vals)) if len(open_vals) > 1 else 0.0)

    if not labels:
        return

    x = range(len(labels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.bar([i - width / 2 for i in x], closed_means, width, yerr=closed_sem, label="closed arms / 닫힌 팔", color="#4e79a7", capsize=4)
    ax.bar([i + width / 2 for i in x], open_means, width, yerr=open_sem, label="open arms / 열린 팔", color="#d37295", capsize=4)
    for i, sex in enumerate(labels):
        pts_closed = [m.pct_closed() for m in groups[sex]]
        pts_open = [m.pct_open() for m in groups[sex]]
        for j, (c, o) in enumerate(zip(pts_closed, pts_open)):
            jitter = (j % 5) * 0.05
            ax.scatter(i - width / 2 + jitter, c, color="#4e79a7", edgecolors="k", zorder=3)
            ax.scatter(i + width / 2 + jitter, o, color="#d37295", edgecolors="k", zorder=3)
    ax.set_ylabel("Occupancy (%) / 점유율")
    if p_val is not None:
        signif = "유의미함" if p_val < 0.05 else "유의미하지 않음"
        ax.set_title(f"EPM occupancy by sex / 성별 점유율\nindependent t-test open% p={p_val:.4f} ({signif})")
    else:
        ax.set_title("EPM occupancy by sex / 성별 점유율")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "epm_open_closed_by_sex.png", bbox_inches="tight")
    plt.close(fig)


def _paired_plot(ax, opens: List[float], closeds: List[float], title: str, p_val: float) -> None:
    import numpy as _np

    bar_x = [0, 1]
    means = [_np.mean(closeds) if closeds else 0.0, _np.mean(opens) if opens else 0.0]
    sems = [
        _np.std(closeds, ddof=1) / math.sqrt(len(closeds)) if len(closeds) > 1 else 0.0,
        _np.std(opens, ddof=1) / math.sqrt(len(opens)) if len(opens) > 1 else 0.0,
    ]
    colors = ["#4e79a7", "#d37295"]
    ax.bar(bar_x, means, yerr=sems, color=colors, capsize=4)
    for i, (o, c) in enumerate(zip(opens, closeds)):
        jitter = (i % 5) * 0.02
        ax.plot([bar_x[0] + jitter, bar_x[1] + jitter], [c, o], color="gray", alpha=0.4)
        ax.scatter([bar_x[0] + jitter], [c], color=colors[0], edgecolors="k", zorder=3)
        ax.scatter([bar_x[1] + jitter], [o], color=colors[1], edgecolors="k", zorder=3)
    ax.set_xticks(bar_x)
    ax.set_xticklabels(["closed", "open"])
    ax.set_ylabel("Occupancy (%) / 점유율")
    signif = "유의미함" if p_val < 0.05 else "유의미하지 않음"
    ax.set_title(f"{title}\npaired t-test p={p_val:.4f} ({signif}) / (대응 t검정)")
    ax.set_ylim(bottom=0, top=100)


def save_paired_by_mouse(mice: List[MouseAgg], out_dir: Path) -> None:
    if not _HAS_MPL:
        return
    opens = [m.pct_open() for m in mice]
    closeds = [m.pct_closed() for m in mice]
    _, _, p_val = paired_t(opens, closeds)
    fig, ax = plt.subplots(figsize=(6, 5))
    _paired_plot(ax, opens, closeds, "Open vs Closed (all mice) / 전체 개체", p_val)
    fig.tight_layout()
    fig.savefig(out_dir / "epm_open_closed_paired_by_mouse.png", bbox_inches="tight")
    plt.close(fig)


def save_paired_by_sex(mice: List[MouseAgg], out_dir: Path) -> None:
    if not _HAS_MPL:
        return
    sexes = {"M": [m for m in mice if m.sex == "M"], "F": [m for m in mice if m.sex == "F"]}
    present = [s for s, group in sexes.items() if group]
    if not present:
        return
    fig, axes = plt.subplots(1, len(present), figsize=(6 * len(present), 5), squeeze=False)
    for idx, sex in enumerate(present):
        group = sexes[sex]
        opens = [m.pct_open() for m in group]
        closeds = [m.pct_closed() for m in group]
        _, _, p_val = paired_t(opens, closeds)
        ax = axes[0][idx]
        _paired_plot(ax, opens, closeds, f"{sex}: Open vs Closed", p_val)
    fig.tight_layout()
    fig.savefig(out_dir / "epm_open_closed_paired_by_sex.png", bbox_inches="tight")
    plt.close(fig)


def save_open_pct_sex(mice: List[MouseAgg], out_dir: Path, p_val: Optional[float]) -> None:
    if not _HAS_MPL:
        return
    males = [m for m in mice if m.sex == "M"]
    females = [m for m in mice if m.sex == "F"]
    labels = []
    means = []
    sems = []
    points = []
    if males:
        labels.append("M")
        vals = [m.pct_open() for m in males]
        means.append(statistics.mean(vals))
        sems.append(statistics.stdev(vals) / math.sqrt(len(vals)) if len(vals) > 1 else 0.0)
        points.append(vals)
    if females:
        labels.append("F")
        vals = [m.pct_open() for m in females]
        means.append(statistics.mean(vals))
        sems.append(statistics.stdev(vals) / math.sqrt(len(vals)) if len(vals) > 1 else 0.0)
        points.append(vals)
    if not labels:
        return
    x = range(len(labels))
    width = 0.5
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.bar(x, means, width, yerr=sems, color="#d37295", capsize=4, label="open arms / 열린 팔")
    for i, vals in enumerate(points):
        for j, v in enumerate(vals):
            jitter = (j % 5) * 0.05
            ax.scatter(i + jitter, v, color="#d37295", edgecolors="k", zorder=3)
    ax.set_ylabel("Open arm occupancy (%) / 열린 팔 점유율")
    if p_val is not None:
        signif = "유의미함" if p_val < 0.05 else "유의미하지 않음"
        ax.set_title(f"Open arm occupancy by sex / 성별 열린 팔 점유율\nindependent t-test p={p_val:.4f} ({signif})")
    else:
        ax.set_title("Open arm occupancy by sex / 성별 열린 팔 점유율")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    fig.tight_layout()
    fig.savefig(out_dir / "epm_open_pct_by_sex.png", bbox_inches="tight")
    plt.close(fig)


def write_aggregated_csv(mice: List[MouseAgg], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "mouse_id",
        "sex",
        "video",
        "open_time_s",
        "closed_time_s",
        "total_time_s",
        "open_pct",
        "closed_pct",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for m in mice:
            writer.writerow(
                {
                    "mouse_id": m.mouse_id,
                    "sex": m.sex or "",
                    "video": m.video,
                    "open_time_s": f"{m.open_time_s:.3f}",
                    "closed_time_s": f"{m.closed_time_s:.3f}",
                    "total_time_s": f"{m.total_time_s:.3f}",
                    "open_pct": f"{m.pct_open():.2f}",
                    "closed_pct": f"{m.pct_closed():.2f}",
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze EPM open vs closed arm occupancy.")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent, help="Directory with *_epm_track_zones.csv files.")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "plots", help="Directory to save plots/CSVs.")
    args = parser.parse_args()

    if _HAS_MPL:
        setup_font(Path(__file__).resolve().parents[2])

    mice = aggregate_mice(args.data_dir)
    if not mice:
        raise SystemExit(f"No *_epm_track_zones.csv found in {args.data_dir}")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    write_aggregated_csv(mice, output_dir / "epm_open_closed_metrics.csv")

    sex_p_val: Optional[float] = None
    males = [m for m in mice if m.sex == "M"]
    females = [m for m in mice if m.sex == "F"]
    if males and females:
        _, _, sex_p = independent_t([m.pct_open() for m in males], [m.pct_open() for m in females])
        sex_p_val = sex_p

    if not _HAS_MPL:
        print("[WARN] matplotlib not available; skipping plots.")
    else:
        save_plot_all(mice, output_dir)
        save_plot_sex(mice, output_dir, p_val=sex_p_val)
        save_paired_by_mouse(mice, output_dir)
        save_paired_by_sex(mice, output_dir)
        save_open_pct_sex(mice, output_dir, sex_p_val)

    def report(label: str, subset: List[MouseAgg]) -> None:
        if not subset:
            print(f"[WARN] {label}: no data")
            return
        opens = [m.pct_open() for m in subset]
        closeds = [m.pct_closed() for m in subset]
        mean_diff, t_stat, p_val = paired_t(opens, closeds)
        print(
            f"{label}: n={len(subset)}  open%={statistics.mean(opens):.2f}  closed%={statistics.mean(closeds):.2f}  "
            f"diff(open-closed)={mean_diff:.2f}  t={t_stat:.3f}  p={p_val:.4f}"
        )

    report("All", mice)
    report("Male", males)
    report("Female", females)
    if sex_p_val is not None:
        print(f"Independent t-test open_pct male vs female: p={sex_p_val:.4f} ({'유의미함' if sex_p_val < 0.05 else '유의미하지 않음'})")


if __name__ == "__main__":
    main()
