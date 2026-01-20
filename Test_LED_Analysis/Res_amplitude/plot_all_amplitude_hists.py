import ROOT
import csv
import math
import os
import re

# --------------------------------------------------
# Paths (EDIT ONLY THESE if needed)
# --------------------------------------------------
BASE_DIR = "/mnt/d/Documents/PhD/EEEMCal_Analysis/Test_LED_Analysis/Res_amplitude"
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR  = os.path.join(BASE_DIR, "images", "amplitudeHist")

os.makedirs(OUT_DIR, exist_ok=True)

ROOT.gROOT.SetBatch(True)

# --------------------------------------------------
# Find files
# --------------------------------------------------
csv_files = sorted(
    f for f in os.listdir(DATA_DIR)
    if f.endswith(".csv") and f.startswith("hist_amplitude_")
)

if not csv_files:
    raise RuntimeError(f"No hist_amplitude_*.csv files found in: {DATA_DIR}")

for csv_file in csv_files:
    csv_path = os.path.join(DATA_DIR, csv_file)

    # Voltage like 1V33 -> 1.33 V
    match = re.search(r"(\d+)V(\d+)", csv_file)
    if match:
        v_int = match.group(1)
        v_dec = match.group(2)
        voltage_value = float(f"{v_int}.{v_dec}")
        voltage_label = f"{voltage_value:.2f} V"
        voltage_tag   = f"{voltage_value:.2f}V"   # safe for ROOT names / filenames
    else:
        voltage_value = None
        voltage_label = "unknown"
        voltage_tag   = "unknown"

    print(f"Processing {csv_file}  (Voltage = {voltage_label})")

    # --------------------------------------------------
    # Read CSV (bin center, counts)
    # --------------------------------------------------
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
    # Histogram (Amplitude)
    # --------------------------------------------------
    hname  = f"h_amp_{voltage_tag}"
    htitle = f"Amplitude Histogram ({voltage_label});Amplitude (mV);Counts"

    h = ROOT.TH1D(hname, htitle, len(x), arr.data())

    for i, c in enumerate(y, start=1):
        h.SetBinContent(i, c)
        h.SetBinError(i, math.sqrt(c) if c >= 0 else 0.0)

    # --------------------------------------------------
    # Compute resolution = RMS/Mean
    # --------------------------------------------------
    mean = h.GetMean()
    rms  = h.GetRMS()
    resolution = (rms / mean) if mean != 0 else 0.0

    # --------------------------------------------------
    # Draw and save
    # --------------------------------------------------
    c1 = ROOT.TCanvas("c1", "c1", 900, 600)
    h.SetLineWidth(2)
    h.Draw("HIST")

    # Text box
    pt = ROOT.TPaveText(0.78, 0.56, 0.98, 0.72, "NDC")
    pt.SetFillColor(0)
    pt.SetBorderSize(1)
    pt.SetTextAlign(12)
    pt.SetTextSize(0.035)

    pt.AddText(f"V = {voltage_label}")
    pt.AddText(f"Mean = {mean:.2f} mV")
    pt.AddText(f"RMS  = {rms:.2f} mV")
    pt.AddText(f"Res = {resolution*100:.2f} %")
    pt.Draw()

    # out_pdf = os.path.join(OUT_DIR, f"hist_amplitude_{voltage_tag}.pdf")
    out_png = os.path.join(OUT_DIR, f"hist_amplitude_{voltage_tag}.png")

    # c1.SaveAs(out_pdf)
    c1.SaveAs(out_png)

    del c1
    del h

print("\n✅ All amplitude histograms processed and saved.")
