import ROOT
import os
from array import array

ROOT.gROOT.SetBatch(True)

DATA_DIR = "beam"
TREE_NAME = "events"

# ============================================================
# Run → Position dictionaries
# ============================================================

run_to_pos_vertical = {
    4: {
        121: 36.2,
        122: 35.2,
        124: 34.2,
        125: 33.2,
        126: 37.2,
        127: 38.2,
        128: 39.2,
        129: 40.2,
    },
}

run_to_pos_horizontal = {
    4: {
        121: 47.2,
        130: 48.2,
        131: 50.2,
        132: 49.2,
        133: 51.2,
        134: 46.2,
        135: 45.2,
        136: 44.2,
        137: 43.2,
    },
}

# ============================================================
# Crystal ↔ hardware mapping
# ============================================================

crystal_map = {
    0: ("210", 1, "c"),
    1: ("211", 0, "a"),
    2: ("209", 0, "c"),
    3: ("211", 1, "a"),
    4: ("209", 1, "a"),
    5: ("209", 0, "b"),
    6: ("208", 1, "d"),
    7: ("210", 1, "a"),
    8: ("211", 1, "d"),
    9: ("210", 0, "a"),
    10: ("209", 1, "d"),
    11: ("210", 0, "c"),
    12: ("210", 0, "d"),
    13: ("209", 1, "b"),
    14: ("209", 0, "d"),
    15: ("210", 0, "b"),
    16: ("208", 0, "c"),
    17: ("211", 0, "b"),
    18: ("208", 1, "c"),
    19: ("210", 1, "b"),
    20: ("209", 1, "c"),
    21: ("208", 1, "b"),
    22: ("208", 0, "a"),
    23: ("210", 1, "d"),
    24: ("209", 0, "a"),
}

fpga_index = {"208": 0, "209": 1, "210": 2, "211": 3}

port_maps = {
    "a": [2, 6, 11, 15, 0, 4, 9, 13, 1, 5, 10, 14, 3, 7, 12, 16],
    "b": [20, 24, 29, 33, 18, 22, 27, 31, 19, 23, 28, 32, 21, 25, 30, 34],
    "c": [67, 63, 59, 55, 69, 65, 61, 57, 70, 66, 60, 56, 68, 64, 58, 54],
    "d": [50, 46, 40, 36, 52, 48, 42, 38, 51, 47, 43, 39, 49, 45, 41, 37],
}

# ============================================================
# Crystal ball
# ============================================================


def make_crystalball(name, xmin, xmax):
    """This function generates the TF1 for a Crystal Ball function.

    Args:
        name (str): name of the function
        xmin (_type_): min x value
        xmax (_type_): max x value
        
    parameters:
        [0] = normalization
        [1] = mean (peak position)
        [2] = sigma (width)
        [3] = alpha (tail transition)
        [4] = n (tail exponent)

    Returns:
        Crystal ball function TF1 to find the center of the crytsal in EEEMCal prototype
    """
    return ROOT.TF1(
        name, "[0]*ROOT::Math::crystalball_function(x,[3],[4],[2],[1])", xmin, xmax
    )


# ============================================================
# Channel builder
# ============================================================


def crystal_channels(crystal_number):
    fpga, asic, port = crystal_map[crystal_number]
    base = 144 * fpga_index[fpga] + 72 * asic
    return [base + ch for ch in port_maps[port]]


# ============================================================
# Per-run analysis
# ============================================================


def analyze_run(run, channels, fit_min=2000, fit_max=2800, prefix=""):
    
    path = os.path.join(DATA_DIR, f"Run{run:03d}.root")
    if not os.path.exists(path):
        print(f"[WARN] Missing file: {path} (skipping)")
        return None

    f = ROOT.TFile.Open(path)
    if not f or f.IsZombie():
        print(f"[WARN] Could not open: {path} (skipping)")
        return None

    tree = f.Get(TREE_NAME)
    if not tree:
        print(f"[WARN] Tree '{TREE_NAME}' not found in {path} (skipping)")
        f.Close()
        return None

    h = ROOT.TH1F(
        f"h_run{run:03d}", f"Run {run}; Σ(ADC − pedestal); Entries", 1000, 0, 10000
    )

    h.Sumw2()

    for event in tree:
        # s = 0.0
        # hm = event.hit_max
        # hp = event.hit_pedestal
        # for ch in channels:
        #     s += hm[ch] - hp[ch]
        s = sum(event.hit_max[ch] - event.hit_pedestal[ch] for ch in channels)
        h.Fill(s)
        
    cb = make_crystalball(f"cb_{run}", fit_min, fit_max)
    
    peak_bin = h.GetMaximumBin() # Bin with the highest content
    peak_x = h.GetXaxis().GetBinCenter(peak_bin) # ADC value at the peak bin
    
    cb.SetParameters(h.GetMaximum(), peak_x, 10.0, 300, 3.0)
    cb.SetParLimits(2, 10, 3000)
    cb.SetParLimits(3, 0.1, 10)
    cb.SetParLimits(4, 1.01, 200)

    c = ROOT.TCanvas(f"c_run{run:03d}", "", 900, 700)
    h.Draw()

    latex = ROOT.TLatex()
    latex.SetNDC()
    latex.SetTextSize(0.04)
    latex.DrawLatex(0.15, 0.82, f"Mean = {mean:.2f} \\pm {mean_err:.2f}")
    if mean != 0:
        latex.DrawLatex(0.15, 0.75, f"Resolution = {sigma/mean*100:.2f} %")
    else:
        latex.DrawLatex(0.15, 0.75, "Resolution = N/A (mean=0)")

    c.SaveAs(os.path.join(OUTPUT_DIR, f"{prefix}run{run:03d}.png"))
    f.Close()

    return mean, mean_err


# ============================================================
# Scan → center extraction
# ============================================================


def extract_center(scan_name: str, run_to_pos, peak_by_run, title, out_png):
    runs = sorted(r for r in run_to_pos.keys() if r in peak_by_run)

    if len(runs) < 3:
        raise RuntimeError(f"Not enough valid points for {scan_name}: got {len(runs)}")

    x = array("d", [run_to_pos[r] for r in runs])
    y = array("d", [peak_by_run[r][0] for r in runs])
    ex = array("d", [0.0] * len(runs))
    ey = array("d", [peak_by_run[r][1] for r in runs])

    c = ROOT.TCanvas(f"c_{scan_name}", "", 900, 700)
    g = ROOT.TGraphErrors(len(runs), x, y, ex, ey)
    g.SetTitle(title)
    g.SetMarkerStyle(21)
    g.Draw("AP")

    f1 = ROOT.TF1(f"f_{scan_name}", "gaus", min(x), max(x))
    g.Fit(f1, "Q")
    f1.SetLineColor(ROOT.kRed)
    f1.Draw("same")

    center = f1.GetParameter(1)
    center_err = f1.GetParError(1)

    latex = ROOT.TLatex()
    latex.SetNDC()
    latex.SetTextSize(0.04)
    latex.DrawLatex(0.15, 0.82, f"Center = {center:.3f} \\pm {center_err:.3f} mm")

    c.SaveAs(out_png)
    return center, center_err


# ============================================================
# Run horizontal + vertical scans
# ============================================================

crystal_number = 4
calib = "W"

FIT_MIN_H, FIT_MAX_H = 3000, 4500
FIT_MIN_V, FIT_MAX_V = 3000, 4500

OUTPUT_DIR = f"center_crystal_{crystal_number:02d}_calib_{calib}"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# ============================================================

channels = crystal_channels(crystal_number)

# Horizontal
peak_H = {}
for run in sorted(run_to_pos_horizontal.keys()):
    res = analyze_run(
        run,
        channels,
        fit_min=FIT_MIN_H,
        fit_max=FIT_MAX_H,
        prefix=f"cr{crystal_number:02d}_H_",
    )
    if res is not None:
        peak_H[run] = res

# Vertical
peak_V = {}
for run in sorted(run_to_pos_vertical.keys()):
    res = analyze_run(
        run,
        channels,
        fit_min=FIT_MIN_V,
        fit_max=FIT_MAX_V,
        prefix=f"cr{crystal_number:02d}_V_",
    )
    if res is not None:
        peak_V[run] = res

x_center, x_err = extract_center(
    scan_name=f"cr{crystal_number:02d}_H",
    run_to_pos=run_to_pos_horizontal,
    peak_by_run=peak_H,
    title=f"Crystal {crystal_number} Horizontal scan; X position (mm); ADC peak",
    out_png=os.path.join(OUTPUT_DIR, f"cr{crystal_number:02d}_H_center.png"),
)

y_center, y_err = extract_center(
    scan_name=f"cr{crystal_number:02d}_V",
    run_to_pos=run_to_pos_vertical,
    peak_by_run=peak_V,
    title=f"Crystal {crystal_number} Vertical scan; Y position (mm); ADC peak",
    out_png=os.path.join(OUTPUT_DIR, f"cr{crystal_number:02d}_V_center.png"),
)

print(f"\nCrystal {crystal_number}")
print(f"  Horizontal center: {x_center:.3f} ± {x_err:.3f} mm")
print(f"  Vertical center:   {y_center:.3f} ± {y_err:.3f} mm")
