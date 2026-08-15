"""Verify the LUFS meter in docs/loudness.html against EBU Tech 3341 test signals.

The functions below are a line-for-line port of the measurement code in the web
tool, so running this checks the numbers the tool actually reports.

Reference: a stereo 1 kHz sine at -23.0 dBFS must read -23.0 LUFS (+/- 0.1).
    https://tech.ebu.ch/docs/tech/tech3341.pdf

Exits non-zero if any measurement falls outside tolerance, so this is
usable as a CI gate and not just a report.

Run:  python tools/verify_lufs.py
"""

import math
import sys

FAILURES = []

def check(label, got, expect, tol):
    ok = abs(got - expect) <= tol
    print(f"{label:34s} -> measured {got:7.2f} LUFS  (expect {expect:6.1f} +/-{tol})  "
          + ("ok" if ok else "FAIL"))
    if not ok:
        FAILURES.append(f"{label}: {got:.2f} vs {expect:.1f} (tol {tol})")

# EXACT port of the coefficients + logic used in docs/loudness.html
def biquad(x,b0,b1,b2,a1,a2):
    y=[0.0]*len(x); x1=x2=y1=y2=0.0
    for i,xi in enumerate(x):
        yi=b0*xi+b1*x1+b2*x2-a1*y1-a2*y2
        x2,x1=x1,xi; y2,y1=y1,yi; y[i]=yi
    return y

def kweight(ch):
    s1=biquad(ch,1.53512485958697,-2.69169618940638,1.19839281085285,-1.69065929318241,0.73248077421585)
    return biquad(s1,1.0,-2.0,1.0,-1.99004745483398,0.99007225036621)

def blocks(chans,rate,win_s,hop_s):
    win=round(win_s*rate); hop=round(hop_s*rate); n=len(chans[0]); out=[]
    start=0
    while start+win<=n:
        z=0.0
        for ch in chans:
            s=sum(v*v for v in ch[start:start+win])
            z+=s/win
        out.append((z,-0.691+10*math.log10(z+1e-12)))
        start+=hop
    return out

def integrated(bl):
    g1=[b for b in bl if b[1]>-70]
    if not g1: return float('-inf')
    mz=sum(b[0] for b in g1)/len(g1)
    rel=-0.691+10*math.log10(mz)-10
    g2=[b for b in g1 if b[1]>rel]
    if not g2: return float('-inf')
    mz2=sum(b[0] for b in g2)/len(g2)
    return -0.691+10*math.log10(mz2)

# EBU Tech 3341 test: stereo 1 kHz sine at -23.0 dBFS  ->  expect -23.0 LUFS (+-0.1)
rate=48000; dur=20.0
for target in (-23.0, -33.0):
    amp=10**(target/20.0)
    n=int(rate*dur)
    sine=[amp*math.sin(2*math.pi*1000*i/rate) for i in range(n)]
    chans=[kweight(sine), kweight(list(sine))]
    I=integrated(blocks(chans,rate,0.4,0.1))
    # Tech 3341 allows +/-0.1 LU on this signal.
    check(f"stereo 1kHz sine @ {target:6.1f} dBFS", I, target, 0.1)

# Gating test: loud -23 dBFS tone with long silence around it.
# The absolute (-70 LUFS) and relative (-10 LU) gates must exclude the silence,
# so integrated loudness should still read ~-23, NOT be dragged down.
amp=10**(-23.0/20.0)
seg=lambda secs,a: [a*math.sin(2*math.pi*1000*i/rate) for i in range(int(rate*secs))]
sig = seg(5,0.0) + seg(10,amp) + seg(5,0.0)
chans=[kweight(sig), kweight(list(sig))]
I=integrated(blocks(chans,rate,0.4,0.1))
# Block edges straddling the silence pull this slightly low, hence 0.3.
check("tone with silence around it", I, -23.0, 0.3)

# Quiet-but-not-silent passage: -23 tone + a -50 dBFS passage.
# Relative gate should exclude the quiet part.
sig2 = seg(10,amp) + seg(10,10**(-50.0/20.0))
chans2=[kweight(sig2), kweight(list(sig2))]
I2=integrated(blocks(chans2,rate,0.4,0.1))
check("tone + quiet -50 dBFS passage", I2, -23.0, 0.3)

if FAILURES:
    print("\n" + str(len(FAILURES)) + " measurement(s) out of tolerance:")
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("\nall LUFS measurements within tolerance")
