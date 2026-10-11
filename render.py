import json, os, re, math, subprocess, urllib.request, urllib.parse
from PIL import Image, ImageDraw, ImageFont

data = json.loads(os.environ["PAYLOAD"])
ai = data["ai"]
fallback_videos = data.get("videos", [])
content = ai["scenes"]
PIX = os.environ.get("PIXABAY_KEY", "")
OAI = os.environ.get("OPENAI_KEY", "")
USE_OPENAI = False  # True = OpenAI voice (needs OPENAI_KEY secret)
VOICE = "ar-EG-ShakirNeural"
FONT = "Amiri"
subject = (ai.get("subject_en") or "").strip()
os.makedirs("output", exist_ok=True)


def run(cmd):
    subprocess.run(cmd, check=True)


def duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path])
    return float(out.decode().strip())


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())


def ts(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return "%d:%02d:%05.2f" % (h, m, s)


def clean(text):
    text = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", text or "")
    text = re.sub(r"[^\u0621-\u064A0-9\s\.\,\!\?\:\-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


used = set()


def search(q):
    url = ("https://pixabay.com/api/videos/?key=" + PIX
           + "&per_page=15&q=" + urllib.parse.quote(q))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        hits = json.loads(r.read().decode())["hits"]
    for h in hits:
        v = h["videos"]
        u = (v.get("large") or {}).get("url") or (v.get("medium") or {}).get("url")
        if u and u not in used:
            used.add(u)
            return u
    return None


def find_video(query, i):
    if PIX:
        for q in [(subject + " " + query).strip(), subject, query, "nature"]:
            if not q:
                continue
            try:
                u = search(q)
                if u:
                    return u
            except Exception as e:
                print("pixabay search failed:", e)
    if fallback_videos:
        return fallback_videos[i % len(fallback_videos)]
    raise SystemExit("no video available")


# ---------- text parts ----------
intro = clean(ai.get("intro"))
outro = clean(ai.get("outro")) or "اشترك في القناة وفعّل الجرس لتصلك كل جديد"
body = [clean(s.get("narration")) for s in content]
body = [b for b in body if b]
queries = [s.get("search_query", "") for s in content if clean(s.get("narration"))]
parts = ([intro] if intro else []) + body + [outro]
kinds = (["intro"] if intro else []) + ["content"] * len(body) + ["outro"]
pq = ([""] if intro else []) + queries + [""]

# ---------- ONE continuous voice ----------
full = " ".join(p if p[-1] in ".!?" else p + "." for p in parts)
with open("full.txt", "w", encoding="utf-8") as f:
    f.write(full)
if USE_OPENAI and OAI:
    body_json = json.dumps({"model": "gpt-4o-mini-tts", "voice": "onyx",
                            "input": full, "response_format": "mp3",
                            "instructions": "Speak Arabic like a calm professional documentary narrator, clear, warm, smooth pacing."}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/audio/speech", data=body_json,
                                 headers={"Authorization": "Bearer " + OAI,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r, open("voice_raw.mp3", "wb") as f:
        f.write(r.read())
else:
    run(["edge-tts", "--voice", VOICE, "--rate=-3%", "--file", "full.txt",
         "--write-media", "voice_raw.mp3"])

run(["ffmpeg", "-y", "-i", "voice_raw.mp3",
 "-af", "silenceremove=start_periods=1:start_threshold=-45dB,loudnorm=I=-16:TP=-1.5:LRA=11",
     "-ar", "44100", "-ac", "2", "voice_n.wav"])
total_voice = duration("voice_n.wav")
lead = 0.4
tail = 2.2  # extra seconds for the subscribe screen after the voice
run(["ffmpeg", "-y", "-i", "voice_n.wav", "-af",
     "adelay=%d|%d,apad=pad_dur=%.2f" % (int(lead * 1000), int(lead * 1000), tail),
     "voice.wav"])

# each part's duration proportional to its text length
lens = [max(8, len(p)) for p in parts]
durs = [total_voice * l / sum(lens) for l in lens]
durs[0] += lead
durs[-1] += tail

# ---------- subscribe screen (drawn, no video) ----------
W, H = 1080, 1920
FPS = 30
AMIRI = "/usr/share/fonts/truetype/hosny-amiri/Amiri-Bold.ttf"
if not os.path.exists(AMIRI):
    AMIRI = subprocess.check_output(["fc-match", "-f", "%{file}", "Amiri:bold"]).decode()


def shape_ar(txt):
    return txt  # libraqm handles shaping when available; plain Amiri works for display


def fnt(size):
    return ImageFont.truetype(AMIRI, size)


def grad_bg():
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        k = y / H
        r = int(14 + 60 * k)
        g = int(18 + 10 * k)
        b = int(52 + 80 * k)
        for x in range(0, W):
            px[x, y] = (r, g, b)
    return img


def draw_text_center(d, txt, y, size, fill):
    f = fnt(size)
    w = d.textlength(txt, font=f)
    d.text(((W - w) / 2, y), txt, font=f, fill=fill, stroke_width=3, stroke_fill=(0, 0, 0))


def bell(d, cx, cy, s, ang):
    # simple bell with swing
    import math as m
    pts = []
    body = [(-1.0, 0.9), (-0.9, 0.2), (-0.6, -0.5), (-0.2, -0.85), (0.2, -0.85),
            (0.6, -0.5), (0.9, 0.2), (1.0, 0.9)]
    for (x, y) in body:
        x2 = x * m.cos(ang) - y * m.sin(ang)
        y2 = x * m.sin(ang) + y * m.cos(ang)
        pts.append((cx + x2 * s, cy + y2 * s))
    d.polygon(pts, fill=(255, 196, 0))
    d.ellipse((cx - s * 0.18 + m.sin(ang) * s * 0.3, cy + s * 0.95,
               cx + s * 0.18 + m.sin(ang) * s * 0.3, cy + s * 1.3), fill=(255, 196, 0))
    d.ellipse((cx - s * 0.12, cy - s * 1.05, cx + s * 0.12, cy - s * 0.8), fill=(255, 196, 0))


def hand(d, x, y, press):
    # stylised pointing hand (finger down), moves by (x, y)
    skin = (255, 214, 170)
    line = (150, 90, 50)
    s = 1.0 - 0.06 * press
    d.rounded_rectangle((x - 38 * s, y - 40 * s, x + 38 * s, y + 130 * s), 30, fill=skin, outline=line, width=4)
    d.rounded_rectangle((x - 40 * s, y + 70 * s, x + 90 * s, y + 210 * s), 40, fill=skin, outline=line, width=4)
    for k in range(3):
        d.rounded_rectangle((x + 20 * s + k * 22 * s, y + 55 * s, x + 44 * s + k * 22 * s, y + 130 * s), 12, fill=skin, outline=line, width=3)
    d.rounded_rectangle((x - 70 * s, y + 90 * s, x - 30 * s, y + 160 * s), 18, fill=skin, outline=line, width=3)


def frame(tsec, base, heart_text):
    img = base.copy()
    d = ImageDraw.Draw(img)
    draw_text_center(d, "لا تنسَ دعمنا", 330, 105, (255, 255, 255))
    draw_text_center(d, "بالاشتراك والجرس", 460, 105, (255, 205, 60))
    # subscribe button pulsing
    pulse = 1 + 0.05 * math.sin(tsec * 8)
    bw, bh = 520 * pulse, 150 * pulse
    cx, cy = W / 2, 880
    d.rounded_rectangle((cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2), 40, fill=(230, 30, 30))
    f = fnt(95)
    label = "اشترك"
    lw = d.textlength(label, font=f)
    d.text((cx - lw / 2, cy - 62), label, font=f, fill=(255, 255, 255))
    # bell swinging
    ang = 0.35 * math.sin(tsec * 9)
    bell(d, W / 2, 1230, 120, ang)
    # moving hand: travels from the right to the button, presses, then to the bell
    cyc = (tsec % 2.4) / 2.4
    if cyc < 0.35:
        k = cyc / 0.35
        hx, hy = 780 - 330 * k, 1150 - 220 * k
        press = 0
    elif cyc < 0.5:
        hx, hy, press = 450, 930, 1
    else:
        k = min(1, (cyc - 0.5) / 0.3)
        hx, hy = 450 + 160 * k, 930 + 220 * k
        press = 1 if cyc > 0.8 else 0
    hand(d, hx, hy, press)
    draw_text_center(d, heart_text, 1560, 80, (255, 255, 255))
    return img
import shutil
os.makedirs("frames", exist_ok=True)
sub_d = durs[-1]
base = grad_bg()
n = int(sub_d * FPS) + 1
for k in range(n):
    frame(k / FPS, base, "شكرًا لمتابعتك").save("frames/f%04d.png" % k)
run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", "frames/f%04d.png",
     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "22",
     "-t", "%.3f" % sub_d, "sub_screen.mp4"])

# ---------- video segments + captions ----------
ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080",
       "PlayResY: 1920", "WrapStyle: 2", "",
       "[V4+ Styles]",
       "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
       "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,"
       "ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
       "MarginL,MarginR,MarginV,Encoding",
       "Style: Default,%s,115,&H00FFFFFF,&H00FFFFFF,"
       "&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,8,3,2,60,60,500,1" % FONT,
       "Style: Hook,%s,125,&H0000E0FF,&H0000E0FF,"
       "&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,9,3,8,60,60,260,1" % FONT,
       "", "[Events]",
       "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]

t = 0.0
vlist = []
for i, (p, kind) in enumerate(zip(parts, kinds)):
    d = durs[i]
    if kind == "outro":
        vlist.append("sub_screen.mp4")
        # caption of outro sentence shown during the voice part only
        voice_part = d - tail
        ws = p.split()
        groups = [" ".join(ws[k:k + 3]) for k in range(0, len(ws), 3)]
        weights = [max(1, len(g)) for g in groups]
        gt = t
        for g, w in zip(groups, weights):
            gd = voice_part * w / sum(weights)
            ass.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (ts(gt), ts(gt + gd), g))
            gt += gd
        t += d
        continue
    clip = "clip%d.mp4" % i
    download(find_video(pq[i], i), clip)
    run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", clip,
         "-t", "%.3f" % d,
         "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,setsar=1,fps=30",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", "sv%d.mp4" % i])
    vlist.append("sv%d.mp4" % i)
    ws = p.split()
    groups = [" ".join(ws[k:k + 3]) for k in range(0, len(ws), 3)]
    weights = [max(1, len(g)) for g in groups]
    speak = d - (lead if i == 0 else 0)
    gt = t + (lead if i == 0 else 0)
    for g, w in zip(groups, weights):
        gd = speak * w / sum(weights)
        ass.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (ts(gt), ts(gt + gd), g))
        gt += gd
    t += d

hook = clean(ai.get("hook"))
if hook:
    ass.append("Dialogue: 1,%s,%s,Hook,,0,0,0,,%s" % (ts(0), ts(3.0), hook))

with open("subs.ass", "w", encoding="utf-8") as f:
    f.write("\n".join(ass))

with open("vlist.txt", "w") as f:
    for v in vlist:
        f.write("file '%s'\n" % v)

run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "vlist.txt",
     "-c", "copy", "joined.mp4"])
run(["ffmpeg", "-y", "-i", "joined.mp4", "-i", "voice.wav",
     "-vf", "subtitles=subs.ass:fontsdir=/usr/share/fonts",
     "-map", "0:v", "-map", "1:a",
     "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
     "-c:a", "aac", "-b:a", "192k", "-shortest", "output/video.mp4"])

with open("output/meta.json", "w", encoding="utf-8") as f:
    json.dump({"title": ai.get("title"), "description": ai.get("description"),
               "tags": ai.get("tags"), "topic": ai.get("topic")},
              f, ensure_ascii=False)
print("DONE")
