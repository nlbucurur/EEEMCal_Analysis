import ROOT
import csv
import math
import os
import re

ROOT.gROOT.SetBatch(True)      # no pop-up canvases
# ROOT.gStyle.SetOptStat(0)     # remove stats box (Mean/RMS box)

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
    htitle = f"Amplitude Histogram ({voltage_label});Amplitude (V);Counts"

    h = ROOT.TH1D(hname, htitle, len(x), arr.data())

    for i, c in enumerate(y, start=1):
        h.SetBinContent(i, c)
        h.SetBinError(i, math.sqrt(c) if c >= 0 else 0.0)
    
    peak_bin = h.GetMaximumBin()
    peak_amp = h.GetBinCenter(peak_bin)
    
    low_edge  = 0.8 * peak_amp
    high_edge = 1.2 * peak_amp
    
    bin_low  = h.FindBin(low_edge)
    bin_high = h.FindBin(high_edge)
    
    # --------------------------------------------------
    # Compute mean/RMS in the selected window only
    # --------------------------------------------------
    
    sumw = 0.0  # Total weight (sum of counts)
    sumwx = 0.0 # Sum of (count × bin_center)
    sumwx2 = 0.0 # Sum of (count × bin_center²)
    
    for b in range(bin_low, bin_high + 1):
        w = h.GetBinContent(b)
        xval = h.GetBinCenter(b)
        sumw += w
        sumwx += w * xval
        sumwx2 += w * xval * xval

    if sumw > 0:
        mean = sumwx / sumw
        var = (sumwx2 / sumw) - mean * mean
        rms = math.sqrt(var) if var > 0 else 0.0
    else:
        mean = 0.0
        rms = 0.0

    resolution = (rms / mean) if mean != 0 else 0.0

    # --------------------------------------------------
    # Crystal Ball fit (fit on a normalized clone)
    # --------------------------------------------------
    
    # # Better initial sigma guess: use your window RMS
    # sigma0 = max(rms, 1e-6)
    # # TF1: [0] = N (norm), [1]=alpha, [2]=n, [3]=mean, [4]=sigma
    
    # Make a clone to fit as a PDF (unit area)
    h_fit = h.Clone(f"{h.GetName()}_fit")
    h_fit.SetDirectory(0)
    
    I = h_fit.Integral("width")
    if I > 0:
        h_fit.Scale(1.0 / I)
    
    fname = f"cb_{voltage_tag}"
    if ROOT.gROOT.FindObject(fname):
        ROOT.gROOT.FindObject(fname).Delete()

    # cb = ROOT.TF1(
    #     fname,
    #     "crystalball",
    #     low_edge,
    #     high_edge
    # )
    
    # Fit function: built-in TF1 "crystalball" has 4 params: alpha, n, mean, sigma
    cb = ROOT.TF1(fname, "crystalball", low_edge, high_edge)
    
    # Better initial sigma guess: use your window RMS (fallback if rms==0)
    sigma0 = rms if rms > 0 else 0.02 * peak_amp
    
    # Initial parameters (VERY important for convergence)
    cb.SetParameters(
        1.5,        # alpha
        3.0,        # n
        peak_amp,   # mean
        sigma0      # sigma
    )
    
    # Parameter limits (stabilizes the fit)
    cb.SetParLimits(0, 0.2, 5.0)                  # alpha
    cb.SetParLimits(1, 1.0, 50.0)                 # n
    cb.SetParLimits(2, low_edge, high_edge)       # mean
    cb.SetParLimits(3, 0.1*sigma0, 10.0*sigma0)   # sigma
    
    # Perform fit
    fit_res = h_fit.Fit(cb, "RQS")  # R=range, Q=quiet, S=store result, 0=no draw
    status = int(fit_res)

    if status != 0:
        print(f"⚠ Fit failed for {csv_file} (status={status}) -> using window RMS/Mean")
        mean_fit = mean
        sigma_fit = rms
    else:
        mean_fit  = cb.GetParameter(2)
        sigma_fit = cb.GetParameter(3)

    resolution_fit = sigma_fit / mean_fit if mean_fit != 0 else 0.0
    

    # # --------------------------------------------------
    # # Compute resolution = RMS/Mean
    # # --------------------------------------------------
    # mean = h.GetMean()
    # rms  = h.GetRMS()
    # resolution = (rms / mean) if mean != 0 else 0.0
    
    # --------------------------------------------------
    # Build a scaled curve to overlay on the ORIGINAL histogram (counts)
    # Scale by matching the peak height
    # --------------------------------------------------
    cb.SetNpx(800)
    
    # If fit succeeded, scale the PDF curve to the histogram counts for display
    if status == 0:
        y_cb_at_peak = cb.Eval(mean_fit)
        scale = (h.GetMaximum() / y_cb_at_peak) if y_cb_at_peak > 0 else 1.0

        xs = ROOT.std.vector('double')()
        ys = ROOT.std.vector('double')()

        npts = 400
        for i in range(npts):
            xx = low_edge + (high_edge - low_edge) * i / (npts - 1)
            xs.push_back(xx)
            ys.push_back(scale * cb.Eval(xx))

        g_cb = ROOT.TGraph(npts, xs.data(), ys.data())
        g_cb.SetLineColor(ROOT.kRed + 2)
        g_cb.SetLineWidth(2)
    else:
        g_cb = None

    del h_fit
    

    # --------------------------------------------------
    # Draw and save
    # --------------------------------------------------
    c1 = ROOT.TCanvas(f"c_{voltage_tag}", f"c_{voltage_tag}", 900, 600)
    c1.SetLogy()
    h.SetLineWidth(2)
    h.Draw("HIST")
    
    # # Draw fit on histogram
    # if status == 0:
    #     cb.SetLineColor(ROOT.kRed + 2)
    #     cb.SetLineWidth(2)
    #     cb.Draw("SAME")
    
    # Draw scaled fit curve (only if fit succeeded)
    if g_cb:
        g_cb.Draw("L SAME")

    # Text box
    pt = ROOT.TPaveText(0.78, 0.56, 0.98, 0.72, "NDC")
    pt.SetFillColor(0)
    pt.SetBorderSize(1)
    pt.SetTextAlign(12)
    pt.SetTextSize(0.025)

    # pt.AddText("Crystal Ball fit")
    pt.AddText(f"V = {voltage_label}")
    pt.AddText(f"Mean = {mean_fit * 1e3:.2f} mV")
    pt.AddText(f"Sigma = {sigma_fit * 1e3:.2f} mV")
    pt.AddText(f"Res = {resolution_fit*100:.2f} %")
    # pt.AddText(f"Window: [{low_edge:.1f}, {high_edge:.1f}] mV")
    pt.Draw()
    
    l1 = ROOT.TLine(low_edge, 0.8, low_edge, h.GetMaximum())
    l2 = ROOT.TLine(high_edge, 0.8, high_edge, h.GetMaximum())
    l1.SetLineStyle(2); l2.SetLineStyle(2)
    l1.SetLineWidth(2); l2.SetLineWidth(2)
    l1.SetLineColorAlpha(ROOT.kOrange + 1, 0.9)
    l2.SetLineColorAlpha(ROOT.kOrange + 1, 0.9)
    l1.Draw("SAME"); l2.Draw("SAME")
    
    # Legend
    if g_cb:
        leg = ROOT.TLegend(0.15, 0.75, 0.45, 0.88)
        leg.SetBorderSize(1)
        leg.SetFillStyle(0)
        leg.AddEntry(h, "Amplitude histogram", "l")
        leg.AddEntry(g_cb, "Crystal Ball fit", "l")
        leg.Draw()

    # out_pdf = os.path.join(OUT_DIR, f"hist_amplitude_{voltage_tag}.pdf")
    out_png = os.path.join(OUT_DIR, f"hist_amplitude_{voltage_tag}_window.png")

    # c1.SaveAs(out_pdf)
    c1.SaveAs(out_png)

    del c1
    del h

print("\n✅ All amplitude histograms processed and saved.")
