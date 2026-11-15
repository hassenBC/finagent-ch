"""Assemble the final video from scene clips with ffmpeg: cards, crossfades, caption overlays, exports.
Run from docs/demo with .tools/bin on PATH. Output: demo.mp4, demo.gif, poster.png (+ build/ intermediates)."""
import subprocess, sys, re, tempfile, os
from pathlib import Path

D = Path(__file__).parent
B = D / "build"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FADE = 0.4
W, H, FPS = 1920, 1080, 30
BG, FG, ACC, MUTED = "0x11111b", "0xcdd6f4", "0x89b4fa", "0xa6adc8"

def ff(*args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)

def txt(s):
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, dir=B, encoding="utf-8"); f.write(s); f.close()
    return f.name

def dt(text, size, color, y, start, dur, font=FONT, x="(w-text_w)/2"):
    """drawtext with fade in at `start` and fade out over the last 0.4s of the clip."""
    a = f"if(lt(t,{start}),0,if(lt(t,{start}+0.5),(t-{start})/0.5,if(gt(t,{dur}-0.4),({dur}-t)/0.4,1)))"
    return f"drawtext=fontfile={font}:textfile={txt(text)}:fontsize={size}:fontcolor={color}:x={x}:y={y}:alpha='{a}'"

def card(name, lines, dur):
    """lines: (text, size, color, y, start, font)."""
    vf = ",".join(dt(t, s, c, y, st, dur, f) for t, s, c, y, st, f in lines)
    ff("-f", "lavfi", "-i", f"color=c={BG}:s={W}x{H}:r={FPS}:d={dur}", "-vf", f"{vf},format=yuv420p", "-t", dur, B / f"{name}.mp4")
    return B / f"{name}.mp4", dur

def vlen(src):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)

def clip(name, src, ss, dur, caption, ui=False):
    dur = round(min(dur, vlen(src) - ss - 0.15), 2)  # never run past the recording
    """Trim a recorded scene, normalise to 1080p30 and add a caption bar that fades in and out."""
    bar_h = 120
    # caption text with its own fade; bar fades in 0.3s after the clip starts and out before the end
    a_in, a_out = 0.5, dur - 0.9
    text = (f"drawtext=fontfile={FONT}:textfile={txt(caption)}:fontsize=44:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2")
    # UI recordings are shrunk to leave a strip under them for the caption, so the caption never hides the answer
    area_h = H - bar_h if ui else H
    cy = H - bar_h if ui else H - bar_h - 40
    graph = (
        f"[0:v]fps={FPS},scale={W}:{area_h}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:0:color={BG},setsar=1,format=yuv420p[v];"
        f"color=c=black@0.72:s={W}x{bar_h}:r={FPS}:d={dur},format=rgba,{text},"
        f"fade=t=in:st={a_in}:d=0.4:alpha=1,fade=t=out:st={a_out}:d=0.4:alpha=1[bar];"
        f"[v][bar]overlay=0:{cy}:format=auto,format=yuv420p[o]"
    )
    ff("-ss", ss, "-i", src, "-t", dur, "-filter_complex", graph, "-map", "[o]", "-r", FPS, B / f"{name}.mp4")
    return B / f"{name}.mp4", dur

C = lambda t, s, c, y, st, f=FONT: (t, s, c, y, st, f)
clips = [
    card("c01_title", [C("finagent-ch", 130, FG, 380, 0.2), C("Ask Swiss bank reports. Get cited, safe answers.", 48, ACC, 560, 0.9, FONT_R)], 3.6),
    card("c02_problem", [
        C("Bank reports run to hundreds of pages.", 56, FG, 330, 0.3),
        C("The numbers hide in tables, in French and English.", 56, FG, 450, 1.8),
        C("AI answers come with no proof, and risky tools.", 56, FG, 570, 3.3),
        C("finagent-ch: cited answers, and guardrails you can test.", 56, ACC, 740, 5.0)], 7.2),
    clip("c03_setup", B / "setup.mp4", 0.3, 8.0, "Start the database, and the assistant is ready."),
    clip("c04_ask", B / "ask.mp4", 0.3, 9.5, "Ask a money question. It looks up the numbers and does the maths."),
    clip("c05_cite", B / "ui_cite.webm", 2.8, 10.0, "Ask in French. Every figure links to the exact report page.", ui=True),
    clip("c06_trace", B / "ui_trace.webm", 2.8, 7.8, "Watch every step: what it searched, and what it can trust.", ui=True),
    clip("c07_approval", B / "ui_approval.webm", 2.8, 14.0, "Risky action? It pauses and asks a human first.", ui=True),
    clip("c08_attack", B / "ui_attack.webm", 2.8, 12.0, "Tricked into leaking data? The safety rules block it.", ui=True),
    card("c09_results", [
        C("Measured, not guessed", 80, FG, 150, 0.2),
        C("Naive baseline  \u2192  final system  (held-out test set, run once)", 34, MUTED, 260, 0.6, FONT_R),
        C("Retrieval recall@5: finding the right page", 40, MUTED, 400, 1.0, FONT_R), C("0.44  →  0.80", 76, ACC, 460, 1.2),
        C("Answer numeric match: correct numbers", 40, MUTED, 600, 2.0, FONT_R), C("0.25  →  0.78", 76, ACC, 660, 2.2),
        C("Citation precision: cited page is right", 40, MUTED, 800, 3.0, FONT_R), C("0.48  →  0.85", 76, ACC, 860, 3.2)], 6.2),
    card("c10_end", [
        C("github.com/hassenBC/finagent-ch", 70, ACC, 330, 0.3),
        C("git clone, then  make setup", 44, FG, 480, 1.0, FONT_R),
        C("Star the repo. Read the report. Try the demo app.", 40, MUTED, 600, 1.6, FONT_R)], 4.6),
]

# crossfade chain
inputs, graph, cum, prev = [], [], 0.0, "[0:v]"
for i, (f, d) in enumerate(clips):
    inputs += ["-i", f]
    if i == 0:
        cum = d; continue
    out = f"[x{i}]"
    off = cum - FADE
    graph.append(f"{prev}[{i}:v]xfade=transition=fade:duration={FADE}:offset={off:.3f}{out}")
    prev, cum = out, off + d
graph.append(f"{prev}format=yuv420p[final]")
print(f"total duration {cum:.1f}s")
ff(*inputs, "-filter_complex", ";".join(graph), "-map", "[final]", "-r", FPS, "-c:v", "libx264", "-preset", "slow",
   "-crf", "27", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", D / "demo.mp4")
ff("-ss", "31", "-i", D / "demo.mp4", "-frames:v", "1", D / "poster.png")
ff("-i", D / "demo.mp4", "-vf", "fps=12,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
   D / "demo.gif")
for f in ("demo.mp4", "demo.gif", "poster.png"):
    print(f, round((D / f).stat().st_size / 1e6, 2), "MB")
