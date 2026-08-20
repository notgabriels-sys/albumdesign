"""Check the true-peak METHOD used in docs/loudness.html (4x oversampling).

Run:  uv run --with numpy --with scipy python tools/verify_truepeak.py

Note: this validates the 4x-oversampling approach with scipy's resampler. The
browser tool uses OfflineAudioContext, whose resampler may differ in the last
decimal, so treat these as method verification rather than a browser measurement.

Classic inter-sample peak case: a 0 dBFS sine at fs/4, phased so every sample
lands at +-0.707. Sample peak reads -3.01 dBFS, but the real waveform peaks at
0 dBFS between samples. A true-peak meter must report ~0 dBTP, not -3.

Exits non-zero if any measurement falls outside tolerance, so this is usable
as a CI gate and not just a report.
"""
import math
import sys

import numpy as np
from scipy.signal import resample_poly

FAILURES = []

def check(label, got, expect, tol, note=""):
    ok = abs(got - expect) <= tol
    print(f"{label:24s}: {got:6.2f} dBTP  (expect {expect:6.2f} +/-{tol})  "
          + ("ok" if ok else "FAIL") + ("   " + note if note else ""))
    if not ok:
        FAILURES.append(f"{label}: {got:.2f} vs {expect:.2f} (tol {tol})")

fs=48000; dur=1.0
n=int(fs*dur)
# sine at fs/4 with 45 degree phase -> samples at +-0.707, true peak 1.0
x=np.array([math.sin(2*math.pi*(fs/4)*i/fs + math.pi/4) for i in range(n)])

def db(v): return 20*math.log10(max(v,1e-12))

sample_peak=np.max(np.abs(x))
# same approach as the web tool: oversample 4x, then take max abs
os4=resample_poly(x,4,1)
true_peak=np.max(np.abs(os4))

# The whole point: the naive reading must be ~3 dB LOW on this signal. If it
# is not, the fixture is wrong and the comparison below proves nothing.
check("sample peak (naive)", db(sample_peak), -3.01, 0.05,
      "<- what a non-true-peak meter shows")
check("true peak (4x oversmp)", db(true_peak), 0.0, 0.15,
      "<- catches the inter-sample peak")
print()
# second case: full-scale sine at a benign frequency should stay ~0
y=np.array([math.sin(2*math.pi*1000*i/fs) for i in range(n)])
check("1 kHz full-scale sine", db(np.max(np.abs(resample_poly(y,4,1)))), 0.0, 0.1)
# third: -1 dBFS sine should read ~-1
z=(10**(-1/20))*y
check("1 kHz sine at -1 dBFS", db(np.max(np.abs(resample_poly(z,4,1)))), -1.0, 0.1)

if FAILURES:
    print("\n" + str(len(FAILURES)) + " measurement(s) out of tolerance:")
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("\ntrue-peak method verified")
