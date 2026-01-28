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

# OUT_DIR = os.path.join(BASE_DIR, "Res_area", "images", "areaHist")
OUT_DIR = BASE_DIR
os.makedirs(OUT_DIR, exist_ok=True)

ROOT.gROOT.SetBatch(True)

# --------------------------------------------------
# Functions
# --------------------------------------------------

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

def weighted_mean_rms_in_bins(h, bin_low, bin_high):
    """Compute weighted mean and RMS using bin contents as weights in [bin_low, bin_high]."""
    sumw = 0.0
    sumwx = 0.0
    sumwx2 = 0.0
    for b in range(bin_low, bin_high + 1):
        w = h.GetBinContent(b)
        xv = h.GetBinCenter(b)
        sumw += w
        sumwx += w * xv
        sumwx2 += w * xv * xv
    if sumw <= 0:
        return 0.0, 0.0, 0.0  # mean, rms, N
    mean = sumwx / sumw
    var = (sumwx2 / sumw) - mean * mean
    rms = math.sqrt(var) if var > 0 else 0.0
    return mean, rms, sumw

def gauss_fit(h, x_min, x_max, mean0, sigma0, fname):
    """
    Fit h with a Gaussian in [x_min, x_max].
    Returns: status, (mean, mean_err), (sigma, sigma_err)
    """
    old = ROOT.gROOT.FindObject(fname)
    if old:
        old.Delete()

    gaus = ROOT.TF1(fname, "gaus", x_min, x_max)
    # gaus params: [0]=amplitude, [1]=mean, [2]=sigma
    gaus.SetParameters(h.GetMaximum(), mean0, sigma0)
    # gaus.SetParLimits(2, 1e-15, (x_max - x_min))  # sigma > 0

    fit_res = h.Fit(gaus, "RQS0")  # R=range, Q=quiet, S=store, 0=no auto draw
    status = int(fit_res)

    if status != 0:
        return status, (None, None), (None, None)

    mean_fit  = gaus.GetParameter(1)
    sigma_fit = gaus.GetParameter(2)
    
    mean_err = gaus.GetParError(1)
    sigma_err = gaus.GetParError(2)

    return status, (mean_fit, mean_err), (sigma_fit, sigma_err)

def res_and_err_from_sigma_mu(sigma, sigma_err, mu, mu_err):
    """Propagate error for R = sigma/mu."""
    if mu == 0 or sigma is None or mu is None:
        return 0.0, 0.0
    R = sigma / mu
    if sigma == 0:
        return R, 0.0
    rel = 0.0
    if sigma_err is not None and mu_err is not None and sigma != 0 and mu != 0:
        rel = math.sqrt((sigma_err / sigma) ** 2 + (mu_err / mu) ** 2)
    return R, abs(R) * rel

# --------------------------------------------------
# Scan files and compute resolution
# --------------------------------------------------
def compute_resolution_points_area(data_dir, file_prefix="hist_area_"):
    """
    Area:
      - Gaussian fit over full x-range
      - resolution = sigma_fit/mean_fit (fallback RMS/Mean if fit fails)
    """
    csv_files = sorted([f for f in os.listdir(data_dir) if f.startswith(file_prefix) and f.endswith(".csv")])
    if not csv_files:
        raise RuntimeError(f"No {file_prefix}*.csv files found in {data_dir}")

    V, Rpct, eV, eRpct = [], [], [], []

    for csv_file in csv_files:
        v_val, v_label, v_tag = parse_voltage(csv_file)
        if v_val is None:
            print(f"⚠ Skipping (cannot parse voltage): {csv_file}")
            continue

        x, y = read_binned_hist_csv(os.path.join(data_dir, csv_file))
        if len(x) < 2:
            print(f"⚠ Skipping (not enough data): {csv_file}")
            continue

        h = make_th1_from_centers_counts(
            x, y,
            hname=f"h_area_{v_tag}",
            htitle=f"Area ({v_label});Area (Wb);Counts"
        )
        if not h:
            print(f"⚠ Skipping (hist build failed): {csv_file}")
            continue
        
        # Fit full range
        x_min = h.GetXaxis().GetXmin()
        x_max = h.GetXaxis().GetXmax()

        mean_rms = h.GetMean()
        rms_rms  = h.GetRMS()
        
        res_rms  = (rms_rms / mean_rms) if mean_rms != 0 else 0.0

        sigma0 = rms_rms if rms_rms > 0 else (0.1 * abs(mean_rms) if mean_rms != 0 else 1.0)

        status, (mu, mu_err), (sig, sigma_err) = gauss_fit(
            h, x_min, x_max,
            mean0=mean_rms,
            sigma0=sigma0,
            fname=f"gaus_area_{v_tag}"
        )

        if status == 0 and mu and mu != 0:
            R, eR = res_and_err_from_sigma_mu(sig, sigma_err, mu, mu_err)
            info = "gaus(full)"
        else:
            # Fallback: RMS/Mean + approximate errors using total counts
            N = h.Integral()
            mu = mean_rms
            sig = rms_rms
            R = (sig / mu) if mu != 0 else 0.0
            mu_err = sig / math.sqrt(N) if N > 0 else 0.0
            sigma_err = sig / math.sqrt(2 * N) if N > 0 else 0.0
            _, eR = res_and_err_from_sigma_mu(sig, sigma_err, mu, mu_err) # extracting only error (ignoring R calculation)
            info = "RMS/Mean(full) [fit failed]"

        V.append(v_val)
        Rpct.append(R * 100.0)
        eV.append(0.0)
        eRpct.append(eR * 100.0)

        print(f"{csv_file:26s} -> V={v_val:.2f}  res={R*100:.2f}% ± {eR*100:.2f}%  ({info})")

        del h

    items = sorted(zip(V, Rpct, eV, eRpct), key=lambda t: t[0])
    if not items:
        raise RuntimeError(f"No valid points found for {file_prefix} in {data_dir}")
    return map(list, zip(*items))

def compute_resolution_points_amp_gaus_window(data_dir, file_prefix="hist_amplitude_", window_factors=(0.8, 1.2)):
    """
    Amplitude:
      - define peak-based window
      - Gaussian fit ONLY in that window
      - resolution = sigma_fit/mean_fit (fallback window RMS/Mean if fit fails)
    """
    csv_files = sorted([f for f in os.listdir(data_dir) if f.startswith(file_prefix) and f.endswith(".csv")])
    if not csv_files:
        raise RuntimeError(f"No {file_prefix}*.csv files found in {data_dir}")

    V, Rpct, eV, eRpct = [], [], [], []

    for csv_file in csv_files:
        v_val, v_label, v_tag = parse_voltage(csv_file)
        if v_val is None:
            print(f"⚠ Skipping (cannot parse voltage): {csv_file}")
            continue

        x, y = read_binned_hist_csv(os.path.join(data_dir, csv_file))
        if len(x) < 2:
            print(f"⚠ Skipping (not enough data): {csv_file}")
            continue

        h = make_th1_from_centers_counts(
            x, y,
            hname=f"h_amp_{v_tag}",
            htitle=f"Amplitude ({v_label});Amplitude (V);Counts"
        )
        if not h:
            print(f"⚠ Skipping (hist build failed): {csv_file}")
            continue

        peak_bin = h.GetMaximumBin()
        peak_x   = h.GetBinCenter(peak_bin)
        low_edge  = window_factors[0] * peak_x
        high_edge = window_factors[1] * peak_x

        bin_low  = h.FindBin(low_edge)
        bin_high = h.FindBin(high_edge)

        mu_w, sig_w, Nw = weighted_mean_rms_in_bins(h, bin_low, bin_high)
        if Nw <= 0 or mu_w == 0:
            print(f"⚠ Skipping (empty/bad window): {csv_file}")
            del h
            continue

        # Fit gaussian in window (fit the ORIGINAL histogram, restricted range)
        sigma0 = sig_w if sig_w > 0 else (0.02 * abs(peak_x))
        
        status, (mu, mu_err), (sig, sig_err) = gauss_fit(
            h, low_edge, high_edge,
            mean0=peak_x,
            sigma0=sigma0,
            fname=f"gaus_amp_{v_tag}"
        )

        if status == 0 and mu is not None and sig is not None:
            R, eR = res_and_err_from_sigma_mu(sig, sig_err, mu, mu_err)
            info = f"gaus(window {low_edge:.3g}-{high_edge:.3g})"
        else:
            # fallback window RMS/Mean with approximations using Nw
            mu = mu_w
            sig = sig_w
            R = (sig / mu) if mu != 0 else 0.0
            mu_err = (sig / math.sqrt(Nw)) if Nw > 0 else 0.0
            sig_err = (sig / math.sqrt(2.0 * Nw)) if Nw > 0 else 0.0
            _, eR = res_and_err_from_sigma_mu(sig, sig_err, mu, mu_err)
            info = f"RMS/Mean(window) [fit failed]"

        V.append(v_val)
        Rpct.append(R * 100.0)
        eV.append(0.0)
        eRpct.append(eR * 100.0)

        print(f"{csv_file:26s} -> V={v_val:.2f}  res={R*100:.2f}% ± {eR*100:.2f}%  ({info})")

        del h

    items = sorted(zip(V, Rpct, eV, eRpct), key=lambda t: t[0])
    if not items:
        raise RuntimeError(f"No valid points found for {file_prefix} in {data_dir}")
    return map(list, zip(*items))

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

vA, rA, evA, erA = compute_resolution_points_area(
    data_dir=AREA_DATA_DIR,
    file_prefix="hist_area_",
)

vP, rP, evP, erP = compute_resolution_points_amp_gaus_window(
    data_dir=AMP_DATA_DIR,
    file_prefix="hist_amplitude_",
    window_factors=(0.8, 1.2)
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
gP.Draw("P SAME")

ymax = max(max(rA), max(rP))
gA.GetYaxis().SetRangeUser(0.0, ymax * 1.1)

# Optional: simple linear fit (comment out if you do not want it)
# fit = ROOT.TF1("fit", "pol1", min(voltages), max(voltages))
# g.Fit(fit, "Q")  # Q = quiet

# Legend
leg = ROOT.TLegend(0.25, 0.75, 0.80, 0.88)
leg.SetBorderSize(1)
leg.SetFillColor(0)
leg.AddEntry(gA, "Area: Gaussian fit (full range) (Wb)", "p")
leg.AddEntry(gP, "Amplitude: Gaussian fit (peak window) (mV)", "p")
leg.SetTextSize(0.035)
leg.Draw()

# Add a small info box
# pt = ROOT.TPaveText(0.76, 0.78, 0.98, 0.88, "NDC")
# pt.SetFillColor(0)
# pt.SetBorderSize(1)
# pt.SetTextSize(0.035)
# pt.AddText(r"Resolution = #sigma/#mu")
# pt.Draw()

# Save
# out_pdf = os.path.join(OUT_DIR, "resolution_vs_voltage_area_and_amplitude.pdf")
out_png = os.path.join(OUT_DIR, "resolution_vs_voltage_area_and_amplitude_gauss.png")
# c.SaveAs(out_pdf)
c.SaveAs(out_png)

# print(f"\n✅ Saved:\n  {out_pdf}\n  {out_png}")
print(f"\n✅ Saved:\n  {out_png}")
