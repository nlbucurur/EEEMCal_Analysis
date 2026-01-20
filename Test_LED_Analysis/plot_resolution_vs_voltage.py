import ROOT
import csv
import math
import os
import re

# --------------------------------------------------
# Paths
# --------------------------------------------------
BASE_DIR = "/mnt/d/Documents/PhD/EEEMCal_Analysis/Test_LED_Analysis"
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR  = os.path.join(BASE_DIR, "images", "areaHist")
os.makedirs(OUT_DIR, exist_ok=True)

ROOT.gROOT.SetBatch(True)

# --------------------------------------------------
# Helpers
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
csv_files = sorted([f for f in os.listdir(DATA_DIR) if f.startswith("hist_area_") and f.endswith(".csv")])
if not csv_files:
    raise RuntimeError(f"No hist_area_*.csv files found in {DATA_DIR}")

voltages = []
resolutions = []
v_errors = []
res_errors = []

for csv_file in csv_files:
    v_val, v_label, v_tag = parse_voltage(csv_file)
    if v_val is None:
        print(f"⚠ Skipping (cannot parse voltage): {csv_file}")
        continue

    csv_path = os.path.join(DATA_DIR, csv_file)
    x, y = read_binned_hist_csv(csv_path)
    if len(x) < 2:
        print(f"⚠ Skipping (not enough data): {csv_file}")
        continue

    h = make_th1_from_centers_counts(
        x, y,
        hname=f"h_{v_tag}",
        htitle=f"Area Histogram ({v_label});Area (Wb);Counts"
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

    print(f"{csv_file:20s} -> V={v_val:.2f}  mean={mean:.3e} Wb  rms={rms:.3e} Wb  res={res*100:.2f}%")

    del h

# Sort by voltage (just in case)
items = sorted(zip(voltages, resolutions, v_errors, res_errors), key=lambda t: t[0])
voltages, resolutions, v_errors, res_errors = map(list, zip(*items))

# --------------------------------------------------
# Make TGraphErrors: Resolution (%) vs Voltage (V)
# --------------------------------------------------
g = ROOT.TGraphErrors(len(voltages))
g.SetName("g_res_vs_v")
g.SetTitle("Resolution vs Voltage;Voltage (V);Resolution (%)")

for i, (v, r, ev, er) in enumerate(zip(voltages, resolutions, v_errors, res_errors)):
    g.SetPoint(i, v, r)
    g.SetPointError(i, ev, er)

# Style
c = ROOT.TCanvas("c_res", "c_res", 900, 600)
g.SetMarkerStyle(20)
g.SetMarkerSize(1.1)
g.SetLineWidth(2)

g.Draw("AP")

# Optional: simple linear fit (comment out if you do not want it)
# fit = ROOT.TF1("fit", "pol1", min(voltages), max(voltages))
# g.Fit(fit, "Q")  # Q = quiet

# Add a small info box
pt = ROOT.TPaveText(0.76, 0.78, 0.98, 0.88, "NDC")
pt.SetFillColor(0)
pt.SetBorderSize(1)
pt.SetTextSize(0.035)
pt.AddText(r"Resolution = \sigma / \mu")
pt.AddText("Area unit: Wb")
pt.Draw()

# Save
out_pdf = os.path.join(OUT_DIR, "resolution_vs_voltage.pdf")
out_png = os.path.join(OUT_DIR, "resolution_vs_voltage.png")
c.SaveAs(out_pdf)
c.SaveAs(out_png)

print(f"\n✅ Saved:\n  {out_pdf}\n  {out_png}")
