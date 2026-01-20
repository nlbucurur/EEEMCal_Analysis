import ROOT
import csv
import math
import os
import re

BASE_DIR = "/mnt/d/Documents/PhD/EEEMCal_Analysis/Test_LED_Analysis"
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR  = os.path.join(BASE_DIR, "images", "areaHist")

os.makedirs(OUT_DIR, exist_ok=True)

ROOT.gROOT.SetBatch(True) # safer in WSL/remote: saves to file instead of opening a window

# --------------------------------------------------
# Loop over CSV files
# --------------------------------------------------
csv_files = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".csv"))

if not csv_files:
    raise RuntimeError("No CSV files found in data directory.")

for csv_file in csv_files:

    csv_path = os.path.join(DATA_DIR, csv_file)

    # Extract voltage from filename (e.g. 1V27)
    match = re.search(r"(\d+)V(\d+)", csv_file)
    if match:
        v_int = match.group(1)
        v_dec = match.group(2)
        voltage_value = float(f"{v_int}.{v_dec}")
        voltage = f"{voltage_value:.2f} V"
    else:
        voltage = "unknown"

    print(f"Processing {csv_file}  (Voltage = {voltage})")

    # --------------------------------------------------
    # Read CSV (bin center, counts)
    # --------------------------------------------------
    x, y = [], []

    with open(csv_path, "r", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
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

    if len(x) < 2:
        print(f"  ⚠ Skipping {csv_file}: not enough valid data")
        continue

    # --------------------------------------------------
    # Build bin edges from bin centers
    # --------------------------------------------------
    edges = [0.0] * (len(x) + 1)
    edges[0] = x[0] - 0.5 * (x[1] - x[0])
    for i in range(1, len(x)):
        edges[i] = 0.5 * (x[i - 1] + x[i])
    edges[-1] = x[-1] + 0.5 * (x[-1] - x[-2])

    arr = ROOT.std.vector("double")()
    for e in edges:
        arr.push_back(e)

    # --------------------------------------------------
    # Histogram
    # --------------------------------------------------
    hname = f"h_area_{voltage}"
    htitle = f"Area Histogram ({voltage});Area (Wb);Counts"

    h = ROOT.TH1D(hname, htitle, len(x), arr.data())

    for i, c in enumerate(y, start=1):
        h.SetBinContent(i, c)
        h.SetBinError(i, math.sqrt(c) if c >= 0 else 0.0)

    # --------------------------------------------------
    # Draw and save
    # --------------------------------------------------
    c1 = ROOT.TCanvas("c1", "c1", 900, 600)
    h.SetLineWidth(2)
    h.Draw("HIST")

    out_pdf = os.path.join(OUT_DIR, f"hist_area_{voltage}.pdf")
    out_png = os.path.join(OUT_DIR, f"hist_area_{voltage}.png")
    
    mean = h.GetMean()
    rms  = h.GetRMS()
    
    resolution = rms / mean if mean != 0 else 0.0
    
    pt = ROOT.TPaveText(0.78, 0.70, 0.98, 0.75, "NDC")
    pt.SetFillColor(0)
    pt.SetBorderSize(1)
    pt.SetTextAlign(12)
    pt.SetTextSize(0.03)

    # pt.AddText(f"Voltage: {voltage}")
    # pt.AddText(f"Mean = {mean:.3e} Wb")
    # pt.AddText(f"RMS  = {rms:.3e} Wb")
    pt.AddText(f"Resolution = {resolution*100:.2f} %")

    pt.Draw()

    c1.SaveAs(out_pdf)
    c1.SaveAs(out_png)

    # Cleanup (important in loops!)
    del c1
    del h

print("\n✅ All histograms processed and saved.")