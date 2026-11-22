"""Flag sudden brightness jumps in a video (a cleanup patch popping, a fill flickering).

Usage: python flicker_check.py <video> [--region x,y,w,h] [--k 6] [--min-jump 1.5] | --self-test
Reads per-frame mean luma (FFmpeg signalstats YAVG) of the frame or a region, takes the frame-to-frame jumps, and flags
a jump larger than k x the median jump and larger than --min-jump (luma levels, 0-255).
Exit 0 none flagged, 1 frames flagged, 2 not checked (no ffmpeg, unreadable video, too few frames, bad arguments).
"""
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def luma_series(video, region=None):
    vf = (f"crop={region[2]}:{region[3]}:{region[0]}:{region[1]}," if region else "") + "signalstats,metadata=print:key=lavfi.signalstats.YAVG"
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vf", vf, "-an", "-f", "null", "-"],
                          capture_output=True, text=True, creationflags=NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"ffmpeg exit {proc.returncode}")
    times = [float(t) for t in re.findall(r"pts_time:([\d.]+)", proc.stderr)]
    values = [float(v) for v in re.findall(r"lavfi\.signalstats\.YAVG=([\d.]+)", proc.stderr)]
    return list(zip(times, values))


def flagged(series, k=6.0, min_jump=1.5):
    jumps = [abs(b[1] - a[1]) for a, b in zip(series, series[1:])]
    # floor of 0.1 luma: a perfectly steady shot has median 0, and any compression wobble would then count as a jump
    base = max(statistics.median(jumps), 0.1)
    return [(series[i + 1][0], j) for i, j in enumerate(jumps) if j > k * base and j > min_jump]


def run(video, region=None, k=6.0, min_jump=1.5):
    if not shutil.which("ffmpeg"):
        print("NOT CHECKED: ffmpeg not on PATH")
        return 2
    try:
        series = luma_series(video, region)
    except (RuntimeError, OSError) as e:
        print(f"NOT CHECKED: {e}")
        return 2
    if len(series) < 3:
        print(f"NOT CHECKED: {len(series)} frame(s) read from {video}")
        return 2
    hits = flagged(series, k, min_jump)
    for t, j in hits:
        print(f"jump {j:6.2f} luma at {t:8.3f}s")
    print(f"{len(series)} frames, {len(hits)} flagged" + (f", region {region}" if region else ""))
    return 1 if hits else 0


def self_test():
    with tempfile.TemporaryDirectory() as d:
        steady, flash = Path(d, "steady.mp4"), Path(d, "flash.mp4")
        base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x120:r=25:d=2"]
        try:
            subprocess.run(base + ["-pix_fmt", "yuv420p", str(steady)], check=True, creationflags=NO_WINDOW)
            subprocess.run(base + ["-vf", "drawbox=x=40:y=30:w=80:h=60:color=white:t=fill:enable='between(n,20,21)'",
                                   "-pix_fmt", "yuv420p", str(flash)], check=True, creationflags=NO_WINDOW)
        except (OSError, subprocess.CalledProcessError) as e:
            print(f"SELF-TEST NOT CHECKED: could not build clips ({e})")
            return 2
        checks = [
            ("steady clip is clean", run(steady) == 0),
            ("flash clip is flagged", run(flash) == 1),
            ("flash outside the region is not flagged", run(flash, region=(0, 0, 30, 30)) == 0),
            ("missing file is not checked", run(Path(d, "none.mp4")) == 2),
        ]
    bad = [n for n, ok in checks if not ok]
    print("SELF-TEST " + ("PASS" if not bad else "FAIL: " + ", ".join(bad)))
    return 0 if not bad else 1


def main(argv):
    if argv == ["--self-test"]:
        return self_test()
    args, region, k, min_jump = [], None, 6.0, 1.5
    it = iter(argv)
    try:
        for a in it:
            if a == "--region":
                region = tuple(int(v) for v in next(it).split(","))
                if len(region) != 4:
                    raise ValueError("region needs x,y,w,h")
            elif a == "--k":
                k = float(next(it))
            elif a == "--min-jump":
                min_jump = float(next(it))
            else:
                args.append(a)
    except (StopIteration, ValueError) as e:
        print(f"bad arguments: {e}\n{__doc__}")
        return 2
    if len(args) != 1:
        print(__doc__)
        return 2
    return run(args[0], region, k, min_jump)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
