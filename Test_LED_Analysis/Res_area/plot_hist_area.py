import ROOT
import csv
import math
import os
import re

ROOT.gROOT.SetBatch(True) # safer in WSL/remote: saves to file instead of opening a window

BASE_DIR = "/mnt/d/Documents/PhD/EEEMCal_Analysis/Test_LED_Analysis/Res_area"
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR  = os.path.join(BASE_DIR, "images", "areaHist")

os.makedirs(OUT_DIR, exist_ok=True)

# --------------------------------------------------
# Helpers
# --------------------------------------------------
def parse_volatage(csv_file):
    """From 'hist_area_1V33.csv' -> (1.33, '1.33 V', '1.33V')"""
    m = re.search(r"(\d+)V(\d+)", csv_file)
    if not m:
        return None, "unknown", "unknown"
    v_val = float(f"{m.group(1)}.{m.group(2)}")
    return v_val, f"{v_val:.2f} V", f"{v_val:.2f}V"

def read_binned_hist_csv(csv_path):
    """Reads CSV with columns: bin_center, counts"""
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
    """Builds a ROOT.TH1D from bin centers (x) and counts (y)"""
    if len(x) < 2:
        return None
    
    # Build bin edges from bin centers
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

# --------------------------------------------------
# Loop over CSV files
# --------------------------------------------------
csv_files = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".csv") and f.startswith("hist_area_"))

if not csv_files:
    raise RuntimeError(f"No CSV files found in: {DATA_DIR}")

for csv_file in csv_files:

    csv_path = os.path.join(DATA_DIR, csv_file)

    v_val, v_label, v_tag = parse_volatage(csv_file)

    print(f"Processing {csv_file}  (Voltage = {v_label})")

    x, y = read_binned_hist_csv(csv_path)
    if len(x) < 2:
        print(f"  ⚠ Skipping {csv_file}: not enough valid data")
        continue

    # --------------------------------------------------
    # Histogram
    # --------------------------------------------------
    hname = f"h_area_{v_tag}"
    htitle = f"Area Histogram ({v_label});Area (Wb);Counts"

    h = make_th1_from_centers_counts(x, y, hname, htitle)
    if not h:
        print(f"  ⚠ Skipping {csv_file}: failed to create histogram")
        continue
    
    # --------------------------------------------------
    # RMS/Mean resolution (full histogram)
    # --------------------------------------------------

    mean = h.GetMean()
    rms  = h.GetRMS()
    
    resolution_rms = rms / mean if mean != 0 else 0.0
    
    # --------------------------------------------------
    # Gaussian fit (full range) -> sigma/mean
    # --------------------------------------------------
    
    x_min = h.GetXaxis().GetXmin()
    x_max = h.GetXaxis().GetXmax()
    
    fname = f"gaus_area_{v_tag}"
    old = ROOT.gROOT.GetFunction(fname)
    if old:
        old.Delete()
    
    gaus = ROOT.TF1(fname, "gaus", x_min, x_max)
    
    # Initial guesses
    sigma0 = rms if rms > 0 else (0.1 * mean if mean != 0 else 1.0)
    gaus.SetParameters(h.GetMaximum(), mean, sigma0)
    
    fit_res = h.Fit(gaus, "RQS0")  # R=use range, Q=quiet, S=return fit result, 0=no drawing
    status = int(fit_res)
    
    if status != 0:
        print(f"⚠ Gaussian fit failed for {csv_file} (status={status}) -> using RMS/Mean")
        mean_fit = mean
        sigma_fit = rms
    else:
        mean_fit  = gaus.GetParameter(1)
        sigma_fit = gaus.GetParameter(2)
        
    resolution_fit = sigma_fit / mean_fit if mean_fit != 0 else 0.0

    # --------------------------------------------------
    # Draw and save
    # --------------------------------------------------
    c1 = ROOT.TCanvas(f"c_area_{v_tag}", f"c_area_{v_tag}", 900, 600)
    h.SetLineWidth(2)
    h.Draw("HIST")
    
    if status == 0:
        gaus.SetLineColor(ROOT.kRed + 2)
        gaus.SetLineWidth(2)
        gaus.Draw("L SAME")
    
    # Text box

    pt = ROOT.TPaveText(0.78, 0.56, 0.98, 0.72, "NDC")
    pt.SetFillColor(0)
    pt.SetBorderSize(1)
    pt.SetTextAlign(12)
    pt.SetTextSize(0.025)

    pt.AddText(f"V = {v_label}")
    if status == 0:
        pt.AddText(f"Mean (fit) = {mean_fit * 1e9:.3f} nWb")
        pt.AddText(f"Sigma (fit) = {sigma_fit * 1e9:.3f} nWb")
        pt.AddText(f"Res (fit) (#sigma/#mu) = {resolution_fit*100:.2f} %")
        # pt.AddText(f"Window: [{low_edge:.1f}, {high_edge:.1f}] mV")
    else:
        pt.AddText(f"Mean = {mean * 1e9:.2f} nWb")
        pt.AddText(f"Sigma = {rms * 1e9:.2f} nWb")
        pt.AddText(f"Res (#sigma/#mu) = {resolution_rms*100:.2f} %")
    pt.Draw()
    
    if status == 0:
        leg = ROOT.TLegend(0.15, 0.75, 0.35, 0.88)
        leg.SetBorderSize(1)
        leg.SetFillStyle(0)
        leg.SetTextSize(0.03)
        leg.AddEntry(h, "Area histogram", "l")
        leg.AddEntry(gaus, "Gaussian fit", "l")
        leg.Draw()

    # out_pdf = os.path.join(OUT_DIR, f"hist_area_{v_tag}.pdf")
    out_png = os.path.join(OUT_DIR, f"hist_area_{v_tag}_gauss.png")
    
    # c1.SaveAs(out_pdf)
    c1.SaveAs(out_png)

    # Cleanup (important in loops!)
    del c1
    del h

print("\n✅ All histograms processed and saved.")