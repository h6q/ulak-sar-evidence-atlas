# AI-assisted code (Claude / Codex / ChatGPT), reviewed and run by Team ULAK.
"""Figures, animation and web assets for the ULAK time-series investigation.

Colour roles follow one fixed scheme across every figure and the web app:
regions use categorical slots (corridor blue, west margin orange, east margin
aqua, AOI-wide neutral grey); changes use a blue <-> red diverging ramp with a
grey midpoint (blue = decrease, red = increase); backscatter uses grey ramps.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

REG_COL = {"corridor": "#2a78d6", "west_margin": "#eb6834", "east_margin": "#1baf7a", "aoi": "#52514e"}
REG_LAB = {"corridor": "Permanent-wetland corridor", "west_margin": "West margin (savanna)",
           "east_margin": "East margin (savanna)", "aoi": "Whole AOI"}
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
DIV = ["#104281", "#2a78d6", "#86b6ef", "#f0efec", "#f2a3a2", "#e34948", "#a52a2a"]
PERS_COL = {1: "#e34948", 2: "#2a78d6", 3: "#eda100", 4: "#f2a3a2", 5: "#86b6ef"}
PERS_LAB = {1: "Persistent increase (raw and normalised)", 2: "Persistent decrease (raw and normalised)",
            3: "Transient exceedance", 4: "Increase in raw only (common-mode)", 5: "Decrease in raw only"}
INTERP_COL = {"water_linked": "#2a78d6", "vegetation_consistent": "#008300", "unresolved": "#c3c2b7", "no_data": None}


def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID,
                         "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                         "axes.titlecolor": INK, "axes.titlesize": 10, "axes.grid": True,
                         "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.facecolor": "white", "axes.facecolor": SURF,
                         "legend.frameon": False, "savefig.dpi": 150})
    return plt


def _div_cmap():
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list("ulak_div", DIV, N=256)


def _dates(results):
    import datetime as dt
    return [dt.date.fromisoformat(d) for d in results["compatibility"]["dates"]]


def _extent_km(arrays):
    tr = arrays["transform"]; H, W = arrays["hh_db"].shape[1:]
    x0, y0 = tr[2] / 1000, tr[5] / 1000
    return [x0, x0 + W * 5 * tr[0] / 1000, y0 + H * 5 * tr[4] / 1000, y0]


FOOT = ("NISAR L2 GCOV PROVISIONAL (P05023), track 86 A, frame 5, freq. A, gamma0; 100 m multilook. "
        "Regions: MODIS IGBP 2023-24. CI: 95% cell-block bootstrap.")


def fig_timeseries(results, out: Path, plt):
    dates = _dates(results)
    for key, title, chg_key in (("hh_db", "HH backscatter", "hh"), ("hv_db", "HV backscatter", "hv"),
                                ("hv_minus_hh_db", "HV/HH ratio (HV - HH)", "hv_minus_hh")):
        fig, axs = plt.subplots(1, 2, figsize=(11, 3.9))
        for name in ("corridor", "west_margin", "east_margin", "aoi"):
            s = results["time_series"][key][name]
            xs = [d for d, v in zip(dates, s) if v and v["median"] is not None]
            ys = [v["median"] for v in s if v and v["median"] is not None]
            lo = [v["lo"] for v in s if v and v["median"] is not None]
            hi = [v["hi"] for v in s if v and v["median"] is not None]
            ls = "--" if name == "aoi" else "-"
            axs[0].plot(xs, ys, ls, color=REG_COL[name], lw=2, marker="o", ms=4, label=REG_LAB[name])
            axs[0].fill_between(xs, lo, hi, color=REG_COL[name], alpha=0.15, lw=0)
            raw = results["change_vs_first"][chg_key]["raw"][name]
            nrm = results["change_vs_first"][chg_key]["normalised"][name]
            xd = [__import__("datetime").date.fromisoformat(r["date"]) for r in raw]
            if name != "aoi":
                axs[1].plot(xd, [r["median"] for r in nrm], "-", color=REG_COL[name], lw=2, marker="o", ms=4,
                            label=REG_LAB[name] + " (normalised)")
                axs[1].fill_between(xd, [r["lo"] for r in nrm], [r["hi"] for r in nrm], color=REG_COL[name], alpha=0.15, lw=0)
        cm = results["change_vs_first"][chg_key]["common_mode"]
        axs[1].plot([__import__("datetime").date.fromisoformat(c["date"]) for c in cm],
                    [c["aoi_median_change_db"] for c in cm], "--", color=REG_COL["aoi"], lw=2, marker="s", ms=4,
                    label="AOI common mode (raw median change)")
        axs[1].axhline(0, color=INK2, lw=0.8)
        axs[0].set_title(f"{title}: region medians of 0.01 deg cell means")
        axs[0].set_ylabel("dB")
        axs[1].set_title("Change vs first date: common mode and region minus common mode")
        axs[1].set_ylabel("dB")
        for a in axs:
            a.tick_params(axis="x", rotation=30)
        axs[0].legend(fontsize=7, loc="best"); axs[1].legend(fontsize=7, loc="best")
        fig.text(0.01, 0.005, FOOT, fontsize=6.5, color=INK2)
        fig.tight_layout(rect=(0, 0.03, 1, 1))
        fig.savefig(out / f"ts_{key}.png"); plt.close(fig)


def fig_change_maps(results, arrays, out: Path, plt):
    cmap = _div_cmap(); ext = _extent_km(arrays)
    dates = arrays["dates"]
    for pol, stack, idx in (("hh", arrays["hh_db"], list(range(len(dates)))), ("hv", arrays["hv_db"], arrays["hv_idx"])):
        pairs = list(zip(idx[:-1], idx[1:]))
        n = len(pairs); ncol = 3; nrow = math.ceil(n / ncol)
        fig, axs = plt.subplots(nrow, ncol, figsize=(10, 3.2 * nrow))
        for k, a in enumerate(np.atleast_1d(axs).ravel()):
            a.grid(False)
            if k >= n:
                a.axis("off"); continue
            i0, i1 = pairs[k]
            im = a.imshow(stack[i1] - stack[i0], cmap=cmap, vmin=-6, vmax=6, extent=ext, interpolation="nearest")
            a.set_title(f"{dates[i0]} -> {dates[i1]}", fontsize=8)
            a.tick_params(labelsize=6)
        fig.colorbar(im, ax=axs, shrink=0.6, label=f"Delta {pol.upper()} (dB); blue decrease, red increase")
        fig.suptitle(f"Consecutive-date {pol.upper()} change (100 m, UTM 36N km)", color=INK)
        fig.text(0.01, 0.005, FOOT, fontsize=6.5, color=INK2)
        fig.savefig(out / f"change_consecutive_{pol}.png"); plt.close(fig)
    # first vs last
    fig, axs = plt.subplots(1, 3, figsize=(12, 4))
    hv0, hv1 = arrays["hv_idx"][0], arrays["hv_idx"][-1]
    ratio = (arrays["hv_db"][hv1] - arrays["hh_db"][hv1]) - (arrays["hv_db"][hv0] - arrays["hh_db"][hv0])
    for a, arr, t in zip(axs, (arrays["d_first_last_hh"], arrays["d_first_last_hv"], ratio),
                         (f"HH {dates[0]} -> {dates[-1]}", f"HV {dates[hv0]} -> {dates[hv1]}", "HV - HH ratio change")):
        a.grid(False)
        im = a.imshow(arr, cmap=cmap, vmin=-6, vmax=6, extent=ext, interpolation="nearest")
        a.set_title(t, fontsize=9); a.tick_params(labelsize=6)
    fig.colorbar(im, ax=axs, shrink=0.75, label="dB (raw, no normalisation)")
    fig.text(0.01, 0.005, FOOT, fontsize=6.5, color=INK2)
    fig.savefig(out / "change_first_last.png"); plt.close(fig)


def fig_trend_persistence(results, arrays, out: Path, plt):
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.patches import Patch
    cmap = _div_cmap(); ext = _extent_km(arrays)
    fig, axs = plt.subplots(2, 2, figsize=(10, 9))
    for a, arr, t in ((axs[0, 0], arrays["slope_hh"], "HH OLS trend"), (axs[0, 1], arrays["slope_hv"], "HV OLS trend")):
        a.grid(False)
        im = a.imshow(arr, cmap=cmap, vmin=-1.5, vmax=1.5, extent=ext, interpolation="nearest")
        a.set_title(t + " (dB per 30 days)", fontsize=9); a.tick_params(labelsize=6)
        fig.colorbar(im, ax=a, shrink=0.8)
    pc = ListedColormap(["#ffffff00", PERS_COL[1], PERS_COL[2], PERS_COL[3], PERS_COL[4], PERS_COL[5]])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5, 5.5], pc.N)
    for a, pol in ((axs[1, 0], "hh"), (axs[1, 1], "hv")):
        a.grid(False)
        m = arrays["pers_maps"][pol].astype(float); m[m == 255] = np.nan
        a.imshow(m, cmap=pc, norm=norm, extent=ext, interpolation="nearest")
        a.set_title(f"{pol.upper()} persistence, |change| > 3 dB vs first date", fontsize=9); a.tick_params(labelsize=6)
    axs[1, 1].legend(handles=[Patch(color=PERS_COL[k], label=PERS_LAB[k]) for k in (1, 2, 4, 5, 3)],
                     fontsize=7, loc="lower left", bbox_to_anchor=(-1.1, -0.32), ncol=3)
    fig.text(0.01, 0.005, FOOT, fontsize=6.5, color=INK2)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(out / "trend_persistence.png"); plt.close(fig)


def fig_regions(results, arrays, out: Path, plt):
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    lab = arrays["ref"].labels
    code = {".": 0, "C": 1, "W": 2, "E": 3}
    m = np.vectorize(code.get)(lab)
    fig, axs = plt.subplots(1, 2, figsize=(10, 4.6))
    ext = [30.55, 30.95, 7.0, 7.4]
    for a in axs:
        a.grid(False)
    axs[0].imshow(m, cmap=ListedColormap(["#ebeae6", REG_COL["corridor"], REG_COL["west_margin"], REG_COL["east_margin"]]),
                  extent=ext, interpolation="nearest", vmin=-0.5, vmax=3.5)
    axs[0].plot(30.55 + (np.array(arrays["ref"].centreline) + 0.0) * 0.01, 7.4 - (np.arange(40) + 0.5) * 0.01,
                color=INK, lw=1, label="Corridor centreline")
    axs[0].set_title("Fixed regions from MODIS IGBP 2023 & 2024 (0.01 deg cells)", fontsize=9)
    axs[0].legend(handles=[Patch(color=REG_COL[k], label=REG_LAB[k]) for k in ("corridor", "west_margin", "east_margin")]
                  + [Patch(color="#ebeae6", label="Unassigned / transition")], fontsize=7, loc="lower right")
    i = arrays["dates"].index(arrays["mdates"][0])
    im = axs[1].imshow(arrays["cell_hh_db"][i], cmap="gray", vmin=-20, vmax=-2, extent=ext, interpolation="nearest")
    axs[1].set_title(f"NISAR HH cell mean {arrays['dates'][i]} (context only)", fontsize=9)
    fig.colorbar(im, ax=axs[1], shrink=0.8, label="dB")
    fig.text(0.01, 0.005, "Regions are defined only from MODIS land cover, never from NISAR change values.", fontsize=7, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "regions.png"); plt.close(fig)


def fig_cross_sensor(results, arrays, out: Path, plt):
    import datetime as dt
    ind = results["independent"]
    s1 = ind["dswx_s1_region_fractions"]; hls = ind["dswx_hls_region_fractions"]
    dates = _dates(results)
    fig, axs = plt.subplots(3, 3, figsize=(12, 8.4), sharex=True)
    for row, name in enumerate(("corridor", "west_margin", "east_margin")):
        s = results["time_series"]["hh_db"][name]; v = results["time_series"]["hv_db"][name]
        axs[row, 0].plot([d for d, x in zip(dates, s) if x], [x["median"] for x in s if x], "-o", color=REG_COL[name], lw=2, ms=4, label="HH")
        axs[row, 0].plot([d for d, x in zip(dates, v) if x], [x["median"] for x in v if x], "--s", color=REG_COL[name], lw=2, ms=4, label="HV")
        axs[row, 0].set_ylabel(f"{REG_LAB[name]}\nNISAR dB", fontsize=8)
        sd = [dt.date.fromisoformat(d) for d in s1 if s1[d][name]["valid_px"]]
        axs[row, 1].plot(sd, [s1[d.isoformat()][name]["inundated_vegetation"] for d in sd], "-o", color="#008300", lw=2, ms=4, label="Inundated vegetation")
        axs[row, 1].plot(sd, [s1[d.isoformat()][name]["open_water"] for d in sd], "-s", color="#2a78d6", lw=2, ms=4, label="Open water")
        axs[row, 1].set_ylabel("DSWx-S1 fraction", fontsize=8); axs[row, 1].set_ylim(0, 1)
        hd = [dt.date.fromisoformat(d) for d in hls if hls[d][name]["clear_fraction"] >= 0.8]
        axs[row, 2].plot(hd, [hls[d.isoformat()][name]["open_water"] for d in hd], "-s", color="#2a78d6", lw=2, ms=4, label="Open water")
        axs[row, 2].plot(hd, [hls[d.isoformat()][name]["partial_surface_water"] for d in hd], "-^", color="#6250d6", lw=2, ms=4, label="Partial surface water")
        axs[row, 2].set_ylabel("DSWx-HLS fraction of clear px", fontsize=8); axs[row, 2].set_ylim(0, 1)
    axs[0, 0].set_title("NISAR L-band (region median)")
    axs[0, 1].set_title("OPERA DSWx-S1 (C-band SAR)")
    axs[0, 2].set_title("OPERA DSWx-HLS (optical; dates >= 80% clear)")
    for a in axs[0]:
        a.legend(fontsize=7)
    for a in axs[-1]:
        a.tick_params(axis="x", rotation=30)
    fig.text(0.01, 0.005, "Independent sensors in separate panels (no shared axis). DSWx-S1 is 1 day before NISAR. "
             "Optical products cannot see water beneath vegetation.", fontsize=7, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "cross_sensor_regions.png"); plt.close(fig)

    # class signatures + temporal association
    fig, axs = plt.subplots(1, 3, figsize=(13, 4.2))
    md = arrays["mdates"]
    for k, (j, a) in enumerate(zip((0, len(md) - 1), axs[:2])):
        d = md[j]; i = arrays["dates"].index(d)
        if i not in arrays["hv_idx"]:
            j = j - 1; d = md[j]; i = arrays["dates"].index(d)
        hh = arrays["cell_hh_db"][i].ravel(); hv = arrays["cell_hv_db"][i].ravel()
        iv = arrays["iv"][j].ravel(); ow = arrays["ow"][j].ravel()
        groups = (("Not water >= 95%", (1 - iv - ow) >= 0.95, "#c3c2b7"), ("Inundated veg. >= 80%", iv >= 0.8, "#008300"),
                  ("Open water >= 80%", ow >= 0.8, "#2a78d6"))
        for lab_, m, col in groups:
            a.scatter(hh[m], hv[m], s=9, color=col, label=f"{lab_} (n={int(m.sum())})", edgecolors="white", linewidths=0.3)
        a.set_xlabel("NISAR HH (dB)"); a.set_ylabel("NISAR HV (dB)")
        a.set_title(f"Cells by DSWx-S1 class: NISAR {d} / S1 {arrays['match'][d]}", fontsize=9)
        a.legend(fontsize=7)
    t = results["independent"]["temporal_association_cells"]
    rho = arrays["full_rho"].ravel()
    rho = rho[np.isfinite(rho)]
    axs[2].hist(rho, bins=np.linspace(-1, 1, 21), color="#2a78d6", edgecolor="white")
    axs[2].set_xlabel("Spearman rho per cell: NISAR HH vs DSWx-S1 (OW+IV)")
    axs[2].set_ylabel("cells")
    txt = (f"cells with water range >= 0.2: {t.get('cells_tested')}\nmedian rho {t.get('median_rho', float('nan')):+.2f}, "
           f"perm. p = {t.get('p_two_sided_median', float('nan')):.3f}\n|rho|>=0.7: {t.get('cells_abs_rho_ge_0.7')} "
           f"(null mean {t.get('null_mean_cells_abs_rho_ge_0.7', float('nan')):.1f})") if "median_rho" in t else t.get("note", "")
    axs[2].text(0.02, 0.97, txt, transform=axs[2].transAxes, va="top", fontsize=7.5, color=INK)
    axs[2].set_title("Temporal association (all cells with data)", fontsize=9)
    fig.tight_layout()
    fig.savefig(out / "cross_sensor_cells.png"); plt.close(fig)


def fig_sensitivity(results, out: Path, plt):
    import datetime as dt
    p = results["persistence"]
    Ts = sorted({float(k.split("_T")[1]) for k in p if "_T" in k and "by_region" not in k})
    fig, axs = plt.subplots(1, 3, figsize=(13, 3.8))
    for pol, ls in (("hh", "-"), ("hv", "--")):
        for kind, col in (("raw", "#eb6834"), ("normalised", "#2a78d6"), ("robust_both", "#0b0b0b")):
            ys = []
            for T in Ts:
                e = p[f"{pol}_T{T:g}"]
                c = e[kind]
                ys.append(100 * (c["persistent_increase"] + c["persistent_decrease"]) / e["valid_px"])
            axs[0].plot(Ts, ys, ls, marker="o", color=col, lw=2, ms=4, label=f"{pol.upper()} {kind}")
    axs[0].set_yscale("log")
    axs[0].set_xlabel("threshold T (dB)"); axs[0].set_ylabel("% of valid area (log)")
    axs[0].set_title("Persistent-change area vs threshold", fontsize=9); axs[0].legend(fontsize=6.5, ncol=2)
    dates = _dates(results)
    cm = results["change_vs_first"]["hh"]["common_mode"]; cmv = results["change_vs_first"]["hv"]["common_mode"]
    axs[1].plot([dt.date.fromisoformat(c["date"]) for c in cm], [c["aoi_median_change_db"] for c in cm], "-o", color="#52514e", lw=2, ms=4, label="HH common mode")
    axs[1].plot([dt.date.fromisoformat(c["date"]) for c in cmv], [c["aoi_median_change_db"] for c in cmv], "--s", color="#6250d6", lw=2, ms=4, label="HV common mode")
    pw = results["independent"]["persistent_open_water_hh_db"]
    if any(v is not None for v in pw):
        base = pw[0]
        axs[1].plot(dates, [v - base if v is not None else None for v in pw], ":^", color="#2a78d6", lw=2, ms=4,
                    label="HH, persistent open-water cells")
    axs[1].axhline(0, color=INK2, lw=0.8)
    axs[1].set_ylabel("dB vs first date"); axs[1].set_title("AOI-wide (common-mode) change", fontsize=9)
    axs[1].legend(fontsize=7); axs[1].tick_params(axis="x", rotation=30)
    r = results["rain"]["antecedent_mm"]
    axs[2].bar(dates, [r[d.isoformat()]["prev7"] or 0 for d in dates], width=4, color="#86b6ef", label="7-day antecedent rain")
    axs[2].bar(dates, [r[d.isoformat()]["prev1"] or 0 for d in dates], width=2, color="#1c5cab", label="previous-day rain")
    axs[2].set_ylabel("mm (NASA POWER, point)"); axs[2].set_title("Rain before each NISAR acquisition", fontsize=9)
    axs[2].legend(fontsize=7); axs[2].tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(out / "sensitivity_and_confounders.png"); plt.close(fig)


def fig_where_why(results, out: Path, plt):
    import datetime as dt
    fig, axs = plt.subplots(1, 3, figsize=(13.5, 4.0))
    prof = results["distance_profile"]
    styles = {"hh_first_last": ("-o", "#e34948", "HH first -> last"), "hv_first_last": ("--s", "#6250d6", "HV first -> last")}
    for key, rows in prof["series"].items():
        ls, col, lab = styles.get(key, (":^", "#eda100", "HH first -> seasonal peak (" + key.split("_")[-1] + ")"))
        xs = [0.5 * (r["from_km"] + r["to_km"]) for r in rows if r["median"] is not None and r["n"] >= 5]
        ys = [r["median"] for r in rows if r["median"] is not None and r["n"] >= 5]
        lo = [r["lo"] for r in rows if r["median"] is not None and r["n"] >= 5]
        hi = [r["hi"] for r in rows if r["median"] is not None and r["n"] >= 5]
        axs[0].plot(xs, ys, ls, color=col, lw=2, ms=4, label=lab)
        axs[0].fill_between(xs, lo, hi, color=col, alpha=0.15, lw=0)
    axs[0].axvline(0, color=INK2, lw=0.8); axs[0].axhline(0, color=INK2, lw=0.8)
    axs[0].set_xlabel("signed distance from corridor centreline (km; west < 0 < east)")
    axs[0].set_ylabel("raw change (dB)")
    axs[0].set_title("Where: change vs distance, savanna cells only", fontsize=9); axs[0].legend(fontsize=7)
    st = results["dswx_strata"]
    cols = {"persistent_open_water": "#2a78d6", "persistent_inundated_veg": "#008300", "persistent_not_water": "#a3a29c"}
    for sname, s in st.items():
        if s["cells"] < 5:
            continue
        for pol, ls in (("hh", "-o"), ("hv", "--s")):
            xs = [dt.date.fromisoformat(r["date"]) for r in s[pol]]
            axs[1].plot(xs, [r["median"] for r in s[pol]], ls, color=cols[sname], lw=2, ms=4,
                        label=f"{pol.upper()} {sname.replace('persistent_', '').replace('_', ' ')} (n={s['cells']})")
    axs[1].axhline(0, color=INK2, lw=0.8)
    axs[1].set_ylabel("raw change vs first date (dB)")
    axs[1].set_title("Strata fixed by DSWx-S1 class on all matched dates", fontsize=9)
    axs[1].legend(fontsize=6.5); axs[1].tick_params(axis="x", rotation=30)
    rain = results["rain"]["antecedent_mm"]
    for name in ("west_margin", "east_margin", "corridor"):
        ch = results["change_vs_first"]["hh"]["raw"][name]
        axs[2].scatter([rain[c["date"]]["prev7"] for c in ch], [c["median"] for c in ch], color=REG_COL[name], s=22,
                       label=REG_LAB[name], edgecolors="white", linewidths=0.4)
        for c in ch:
            axs[2].annotate(c["date"][5:], (rain[c["date"]]["prev7"], c["median"]), fontsize=5.5, color=INK2,
                            xytext=(2, 2), textcoords="offset points")
    axs[2].set_xlabel("7-day antecedent rain (mm, NASA POWER)"); axs[2].set_ylabel("raw HH change vs first date (dB)")
    axs[2].set_title("Why (partly): HH change vs recent rain", fontsize=9); axs[2].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "where_and_why.png"); plt.close(fig)


def _gray(arr, lo, hi):
    v = np.clip((arr - lo) / (hi - lo), 0, 1)
    g = (np.nan_to_num(v, nan=0.0) * 255).astype(np.uint8)
    rgba = np.dstack([g, g, g, np.where(np.isfinite(arr), 255, 0).astype(np.uint8)])
    return rgba


def animation(arrays, out: Path, log=print):
    from PIL import Image, ImageDraw
    frames = []
    for pol, stack, idx, lo, hi in (("HH", arrays["hh_db"], range(len(arrays["dates"])), -22, -2),):
        for i in idx:
            rgba = _gray(stack[i], lo, hi)
            im = Image.fromarray(rgba[..., :3]).resize((stack.shape[2] * 2, stack.shape[1] * 2), Image.NEAREST)
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, 360, 26], fill=(255, 255, 255))
            d.text((6, 6), f"NISAR {pol} gamma0  {arrays['dates'][i]}  (-22..-2 dB)", fill=(11, 11, 11))
            frames.append(im)
    frames[0].save(out / "animation_hh.gif", save_all=True, append_images=frames[1:], duration=900, loop=0)
    log(f"wrote {out / 'animation_hh.gif'} ({len(frames)} frames)")


def make_all(results, arrays, out: Path, log=print):
    out.mkdir(parents=True, exist_ok=True)
    plt = _mpl()
    fig_regions(results, arrays, out, plt)
    fig_timeseries(results, out, plt)
    fig_change_maps(results, arrays, out, plt)
    fig_trend_persistence(results, arrays, out, plt)
    fig_cross_sensor(results, arrays, out, plt)
    fig_sensitivity(results, out, plt)
    fig_where_why(results, out, plt)
    animation(arrays, out, log=log)
    log(f"figures in {out}")


# ---------------------------------------------------------------------------- web

def _div_rgba(arr, vmax):
    from matplotlib.colors import to_rgb
    cols = np.array([to_rgb(c) for c in DIV])
    v = np.clip((arr + vmax) / (2 * vmax), 0, 1) * (len(DIV) - 1)
    i0 = np.floor(np.nan_to_num(v)).astype(int).clip(0, len(DIV) - 2)
    f = (np.nan_to_num(v) - i0)[..., None]
    rgb = (cols[i0] * (1 - f) + cols[i0 + 1] * f) * 255
    a = np.where(np.isfinite(arr), 230, 0).astype(np.uint8)
    return np.dstack([rgb.astype(np.uint8), a])


def write_web(results, arrays, web_dir: Path, log=print):
    from PIL import Image
    from matplotlib.colors import to_rgb
    sys_path = Path(__file__).resolve().parent
    import sys
    sys.path.insert(0, str(sys_path))
    from report_builder import _reproject_to_4326
    from rasterio.transform import Affine
    tr = arrays["transform"]
    t100 = Affine(tr[0] * 5, 0, tr[2], 0, tr[4] * 5, tr[5])
    ts_dir = web_dir / "ts"
    ts_dir.mkdir(parents=True, exist_ok=True)
    overlays = {"frames": [], "layers": {}}

    def save(name, rgba):
        Image.fromarray(rgba, "RGBA").save(ts_dir / name, optimize=True)

    bounds = None
    for i, d in enumerate(arrays["dates"]):
        for pol, stack, lo, hi in (("hh", arrays["hh_db"], -22, -2), ("hv", arrays["hv_db"], -30, -12)):
            if pol == "hv" and i not in arrays["hv_idx"]:
                continue
            dst, bounds = _reproject_to_4326(stack[i].astype("float32"), t100, arrays["epsg"], nearest=False)
            save(f"{pol}_{d}.png", _gray(dst, lo, hi))
        overlays["frames"].append({"date": d, "hh": f"ts/hh_{d}.png",
                                   "hv": f"ts/hv_{d}.png" if i in arrays["hv_idx"] else None})
    for name, arr, vmax, desc in (("delta_hh_first_last", arrays["d_first_last_hh"], 6, "HH change first->last, dB (-6 blue .. +6 red)"),
                                  ("delta_hv_first_last", arrays["d_first_last_hv"], 6, "HV change first->last, dB (-6 blue .. +6 red)"),
                                  ("trend_hh", arrays["slope_hh"], 1.5, "HH OLS trend, dB per 30 days (-1.5 .. +1.5)"),
                                  ("trend_hv", arrays["slope_hv"], 1.5, "HV OLS trend, dB per 30 days (-1.5 .. +1.5)")):
        dst, b = _reproject_to_4326(arr.astype("float32"), t100, arrays["epsg"], nearest=False)
        save(f"{name}.png", _div_rgba(dst, vmax))
        overlays["layers"][name] = {"file": f"ts/{name}.png", "bounds_latlon": b, "render": desc}
    for pol in ("hh", "hv"):
        dst, b = _reproject_to_4326(arrays["pers_maps"][pol], t100, arrays["epsg"], nearest=True)
        rgba = np.zeros(dst.shape + (4,), np.uint8)
        for k, c in PERS_COL.items():
            m = dst == k
            rgba[m, :3] = (np.array(to_rgb(c)) * 255).astype(np.uint8); rgba[m, 3] = 220
        save(f"persistence_{pol}.png", rgba)
        overlays["layers"][f"persistence_{pol}"] = {"file": f"ts/persistence_{pol}.png", "bounds_latlon": b,
                                                    "render": "persistence classes (see legend)"}
    overlays["frame_bounds_latlon"] = bounds

    def r2(a):
        return [[None if not np.isfinite(v) else round(float(v), 2) for v in row] for row in a]
    ref = arrays["ref"]
    cells = {
        "grid": {"aoi_wsen": [30.55, 7.0, 30.95, 7.4], "deg": 0.01, "rows": 40, "cols": 40, "row0": "north"},
        "labels": ["".join(r) for r in ref.labels],
        "interpretation": [[arrays["interp"][r, c] for c in range(40)] for r in range(40)],
        "hh_db": [r2(a) for a in arrays["cell_hh_db"]],
        "hv_db": [r2(a) if i in arrays["hv_idx"] else None for i, a in enumerate(arrays["cell_hv_db"])],
        "dswx_dates": [arrays["match"][d] for d in arrays["mdates"]],
        "dswx_iv": [[[round(float(v), 2) for v in row] for row in a] for a in arrays["iv"]],
        "dswx_ow": [[[round(float(v), 2) for v in row] for row in a] for a in arrays["ow"]],
        "rho_hh_vs_water": r2(arrays["full_rho"]),
        "hv_theil_sen_db_per_30d": r2(arrays["hv_slope"]),
        "modis_stable_wet_pct": ref.wet4.tolist(), "modis_stable_savanna_pct": ref.sav4.tolist(),
    }
    keep = {k: results[k] for k in ("schema", "software", "generated_utc", "data_status", "product", "compatibility",
                                    "regions", "noise", "time_series", "change_vs_first", "region_differentials_first_last",
                                    "range_dependence_check", "rain", "interpretation", "decision_gate",
                                    "distance_profile", "dswx_strata", "sensitivity_including_excluded_dates",
                                    "uncertainty_methods")}
    keep["persistence"] = {k: v for k, v in results["persistence"].items()}
    keep["independent"] = {k: results["independent"][k] for k in ("dswx_s1_match", "dswx_s1_region_fractions",
                                                                 "dswx_hls_region_fractions", "class_signatures",
                                                                 "change_association", "temporal_association_cells",
                                                                 "temporal_association_regions")}
    keep["overlays"] = overlays
    keep["cells"] = cells
    (web_dir / "timeseries.json").write_text(json.dumps(keep, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    log(f"wrote {web_dir / 'timeseries.json'} and {len(list(ts_dir.glob('*.png')))} PNGs")
