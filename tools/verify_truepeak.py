"""Check the true-peak METHOD used in docs/loudness.html (4x oversampling).

Run:  uv run --with numpy --with scipy python tools/verify_truepeak.py

Note: this validates the 4x-oversampling approach with scipy's resampler. The
browser tool uses OfflineAudioContext, whose resampler may differ in the last
decimal, so treat these as method verification rather than a browser measurement.

Classic inter-sample peak case: a 0 dBFS sine at fs/4, phased so every sample
lands at +-0.707. Sample peak reads -3.01 dBFS, but the real waveform peaks at
0 dBFS between samples. A true-peak meter must report ~0 dBTP, not -3.
"""
import math
import numpy as np
from scipy.signal import resample_poly

fs=48000; dur=1.0
n=int(fs*dur)
# sine at fs/4 with 45 degree phase -> samples at +-0.707, true peak 1.0
x=np.array([math.sin(2*math.pi*(fs/4)*i/fs + math.pi/4) for i in range(n)])

def db(v): return 20*math.log10(max(v,1e-12))

sample_peak=np.max(np.abs(x))
# same approach as the web tool: oversample 4x, then take max abs
os4=resample_poly(x,4,1)
true_peak=np.max(np.abs(os4))

print(f"sample peak (naive)   : {db(sample_peak):6.2f} dBFS   <- what a non-true-peak meter shows")
print(f"true peak  (4x oversmp): {db(true_peak):6.2f} dBTP   <- expect ~0.00, tolerance ~0.1")
print()
# second case: full-scale sine at a benign frequency should stay ~0
y=np.array([math.sin(2*math.pi*1000*i/fs) for i in range(n)])
print(f"1 kHz full-scale sine  : {db(np.max(np.abs(resample_poly(y,4,1)))):6.2f} dBTP   (expect ~0.00)")
# third: -1 dBFS sine should read ~-1
z=(10**(-1/20))*y
print(f"1 kHz sine at -1 dBFS  : {db(np.max(np.abs(resample_poly(z,4,1)))):6.2f} dBTP   (expect ~-1.00)")
