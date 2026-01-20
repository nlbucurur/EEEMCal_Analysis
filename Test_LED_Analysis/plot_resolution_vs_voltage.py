import ROOT
import csv
import math
import os
import re

# --------------------------------------------------
# Paths
# --------------------------------------------------
BASE_DIR = "/mnt/d/Documents/PhD/EEEMCal_Analysis/Test_LED_Analysis"

AREA_DATA_DIR = os.path.join(BASE_DIR, "Res_area", "data")
AMP_DATA_DIR  = os.path.join(BASE_DIR, "Res_amplitude", "data")

OUT_DIR = os.path.join(BASE_DIR, "Res_area", "images", "areaHist")
os.makedirs(OUT_DIR, exist_ok=True)

ROOT.gROOT.SetBatch(True)

# --------------------------------------------------
# Functions
# --------------------------------------------------
def read_binned_hist_csv(csv_path):
    """Reads CSV with columns: bin_center, counts (header allowed). Returns (x_centers, counts)."""
    x, y = [], []
    with open(csv_path, "r", newline="") as f:
        reader = csv.reader(f)
        _ = next(reader, None)  # skip header if present
        for row in reader:
            if not row or len(row) < 2:
                continue
            try:
                xc = float(row[0])
                c  = float(row[1])
            except ValueError:
                continue
            if math.isnan(xc) or math.isnan(c):
                continue
            x.append(xc)
            y.append(c)
    return x, y

def make_th1_from_centers_counts(x, y, hname, htitle):
    """Build TH1D with variable binning from centers, set bin contents."""
    if len(x) < 2:
        return None

    edges = [0.0] * (len(x) + 1)
    edges[0] = x[0] - 0.5 * (x[1] - x[0])
    for i in range(1, len(x)):
        edges[i] = 0.5 * (x[i - 1] + x[i])
    edges[-1] = x[-1] + 0.5 * (x[-1] - x[-2])

    arr = ROOT.std.vector("double")()
    for e in edges:
        arr.push_back(e)

    h = ROOT.TH1D(hname, htitle, len(x), arr.data())
    for i, c in enumerate(y, start=1):
        h.SetBinContent(i, c)
        h.SetBinError(i, math.sqrt(c) if c >= 0 else 0.0)
    return h

def parse_voltage(csv_file):
    """
    From 'hist_area_1V33.csv' -> (1.33, '1.33 V', '1.33V')
    """
    m = re.search(r"(\d+)V(\d+)", csv_file)
    if not m:
        return None, "unknown", "unknown"
    v_int, v_dec = m.group(1), m.group(2)
    v_val = float(f"{v_int}.{v_dec}")
    return v_val, f"{v_val:.2f} V", f"{v_val:.2f}V"

# --------------------------------------------------
# Scan files and compute resolution
# --------------------------------------------------
def compute_resolution_points(data_dir, file_prefix, x_unit_label):
    """
    Reads histograms in data_dir matching f"{file_prefix}_*.csv",
    computes resolution = RMS/Mean (in %), and returns sorted arrays:
    voltages, resolutions_pct, v_errors, res_errors_pct
    """
    
    csv_files = sorted([f for f in os.listdir(data_dir) if f.startswith(file_prefix) and f.endswith(".csv")])
    if not csv_files:
        raise RuntimeError(f"No {file_prefix}*.csv files found in {data_dir}")

    voltages = []
    resolutions = []
    v_errors = []
    res_errors = []

    for csv_file in csv_files:
        v_val, v_label, v_tag = parse_voltage(csv_file)
        if v_val is None:
            print(f"⚠ Skipping (cannot parse voltage): {csv_file}")
            continue

        csv_path = os.path.join(data_dir, csv_file)
        x, y = read_binned_hist_csv(csv_path)
        if len(x) < 2:
            print(f"⚠ Skipping (not enough data): {csv_file}")
            continue

        h = make_th1_from_centers_counts(
            x, y,
            hname=f"h_{file_prefix}_{v_tag}",
            htitle=f"{file_prefix} ({v_label});{x_unit_label};Counts"
        )
        if not h:
            print(f"⚠ Skipping (hist build failed): {csv_file}")
            continue

        mean = h.GetMean()
        rms  = h.GetRMS()

        mean_err = h.GetMeanError()
        rms_err  = h.GetRMSError()

        if mean == 0 or math.isnan(mean) or math.isnan(rms):
            print(f"⚠ Skipping (bad mean/rms): {csv_file}  mean={mean} rms={rms}")
            continue

        res = rms / mean

        # Error propagation for res = rms/mean
        # res_err/res = sqrt( (rms_err/rms)^2 + (mean_err/mean)^2 )
        if rms > 0:
            rel = math.sqrt((rms_err / rms) ** 2 + (mean_err / mean) ** 2) if mean != 0 else 0.0
            res_err = abs(res) * rel
        else:
            res_err = 0.0

        voltages.append(v_val)
        resolutions.append(res * 100.0)      # in %
        v_errors.append(0.0)                 # no voltage uncertainty provided
        res_errors.append(res_err * 100.0)   # in %

        print(f"{csv_file:26s} -> V={v_val:.2f}  mean={mean:.3e}  rms={rms:.3e}  res={res*100:.2f}%")

        del h

    # Sort by voltage (just in case)
    items = sorted(zip(voltages, resolutions, v_errors, res_errors), key=lambda t: t[0])
    if not items:
        raise RuntimeError(f"No valid points gound for {file_prefix} in {data_dir}")
    voltages, resolutions, v_errors, res_errors = map(list, zip(*items))
    return voltages, resolutions, v_errors, res_errors

# --------------------------------------------------
# Make TGraphErrors: Resolution (%) vs Voltage (V)
# --------------------------------------------------
def make_graph(name, title, voltages, resolutions, v_errors, res_errors):
    g = ROOT.TGraphErrors(len(voltages))
    g.SetName(name)
    g.SetTitle(title)
    for i, (v, r, ev, er) in enumerate(zip(voltages, resolutions, v_errors, res_errors)):
        g.SetPoint(i, v, r)
        g.SetPointError(i, ev, er)
    return g

# --------------------------------------------------
# Compute curves
# --------------------------------------------------

vA, rA, evA, erA = compute_resolution_points(
    data_dir=AREA_DATA_DIR,
    file_prefix="hist_area_",
    x_unit_label="Area (Wb)"
)

vP, rP, evP, erP = compute_resolution_points(
    data_dir=AMP_DATA_DIR,
    file_prefix="hist_amplitude_",
    x_unit_label="Amplitude (mV)"
)

# --------------------------------------------------
# Build graphs
# --------------------------------------------------

gA = make_graph(
    name="g_res_area",
    title="Resolution vs Voltage;Voltage (V);Resolution (%)",
    voltages=vA, resolutions=rA, v_errors=evA, res_errors=erA
)

gP = make_graph(
    name="g_res_amp",
    title="Resolution vs Voltage;Voltage (V);Resolution (%)",
    voltages=vP, resolutions=rP, v_errors=evP, res_errors=erP
)

# Style
# Area (blue)
gA.SetMarkerStyle(20)
gA.SetMarkerSize(1.1)
gA.SetLineWidth(2)
gA.SetMarkerColor(ROOT.kBlue + 1)
gA.SetLineColor(ROOT.kBlue + 1)

# Amplitude (red)
gP.SetMarkerStyle(21)
gP.SetMarkerSize(1.1)
gP.SetLineWidth(2)
gP.SetMarkerColor(ROOT.kRed + 1)
gP.SetLineColor(ROOT.kRed + 1)

c = ROOT.TCanvas("c_res", "c_res", 900, 600)
gA.Draw("AP")

ymax = max(max(rA), max(rP))
gA.GetYaxis().SetRangeUser(0.0, ymax * 1.1)

gP.Draw("P SAME")
# Optional: simple linear fit (comment out if you do not want it)
# fit = ROOT.TF1("fit", "pol1", min(voltages), max(voltages))
# g.Fit(fit, "Q")  # Q = quiet

# Legend
leg = ROOT.TLegend(0.25, 0.75, 0.50, 0.88)
leg.SetBorderSize(1)
leg.SetFillColor(0)
leg.AddEntry(gA, "From Area Histogram (Wb)", "p")
leg.AddEntry(gP, "From Amplitude Histogram (mV)", "p")
leg.Draw()

# Add a small info box
pt = ROOT.TPaveText(0.76, 0.78, 0.98, 0.88, "NDC")
pt.SetFillColor(0)
pt.SetBorderSize(1)
pt.SetTextSize(0.035)
pt.AddText(r"Resolution = \sigma / \mu")
pt.Draw()

# Save
# out_pdf = os.path.join(OUT_DIR, "resolution_vs_voltage_area_and_amplitude.pdf")
out_png = os.path.join(OUT_DIR, "resolution_vs_voltage_area_and_amplitude.png")
# c.SaveAs(out_pdf)
c.SaveAs(out_png)

# print(f"\n✅ Saved:\n  {out_pdf}\n  {out_png}")
print(f"\n✅ Saved:\n  {out_png}")
