import json, os, re, math, time, subprocess, urllib.request, urllib.parse
from PIL import Image, ImageDraw, ImageFont

data = json.loads(os.environ["PAYLOAD"])
ai = data["ai"]
fallback_videos = data.get("videos", [])
content = ai["scenes"]
PIX = os.environ.get("PIXABAY_KEY", "")
OAI = os.environ.get("OPENAI_KEY", "")
OPENAI_VOICE = "onyx"
FONT = "Amiri"
subject = (ai.get("subject_en") or "").strip()
os.makedirs("output", exist_ok=True)


def run(cmd):
    subprocess.run(cmd, check=True)


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path])
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
    url = "https://pixabay.com/api/videos/?key=" + PIX + "&per_page=15&q=" + urllib.parse.quote(q)
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


def tts(text, out_mp3):
    if not OAI:
        raise SystemExit("OPENAI_KEY secret is missing in GitHub")
    payload = {"model": "gpt-4o-mini-tts", "voice": OPENAI_VOICE, "input": text, "response_format": "mp3", "instructions": "Speak Arabic like a calm professional documentary narrator, clear, warm, smooth pacing. Keep the same tone and speed throughout, with a natural flowing rhythm."}
    body_json = json.dumps(payload).encode()
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request("https://api.openai.com/v1/audio/speech", data=body_json, headers={"Authorization": "Bearer " + OAI, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r, open(out_mp3, "wb") as f:
                f.write(r.read())
            return
        except Exception as e:
            last = e
            print("openai tts failed:", e)
            time.sleep(5)
    raise SystemExit("openai tts failed: %s" % last)


intro = clean(ai.get("intro"))
outro = clean(ai.get("outro")) or "اشترك في القناة وفعّل الجرس لتصلك كل جديد"
body = [clean(s.get("narration")) for s in content]
body = [b for b in body if b]
queries = [s.get("search_query", "") for s in content if clean(s.get("narration"))]
parts = ([intro] if intro else []) + body + [outro]
kinds = (["intro"] if intro else []) + ["content"] * len(body) + ["outro"]
pq = ([""] if intro else []) + queries + [""]

# ---------- one voice file per sentence, measured exactly ----------
GAP = 0.12
lead = 0.4
tail = 3.0
seg_dur = []
for i, p in enumerate(parts):
    text = p if p[-1] in ".!?" else p + "."
    tts(text, "raw%d.mp3" % i)
    run(["ffmpeg", "-y", "-i", "raw%d.mp3" % i, "-af", "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "2", "seg%d.wav" % i])
    seg_dur.append(duration("seg%d.wav" % i))

# build the final voice track with exact silence offsets
run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "%.3f" % lead, "lead.wav"])
run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "%.3f" % GAP, "gap.wav"])
run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "%.3f" % tail, "tail.wav"])
with open("alist.txt", "w") as f:
    f.write("file 'lead.wav'\n")
    for i in range(len(parts)):
        f.write("file 'seg%d.wav'\n" % i)
        if i < len(parts) - 1:
            f.write("file 'gap.wav'\n")
    f.write("file 'tail.wav'\n")
run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "alist.txt", "-ar", "44100", "-ac", "2", "voice.wav"])

# exact start/end of each sentence on the final timeline
starts = []
ends = []
cur = lead
for i in range(len(parts)):
    starts.append(cur)
    cur += seg_dur[i]
    ends.append(cur)
    cur += GAP

# video segment durations: each scene covers its sentence + gap (first one also the lead)
durs = []
for i in range(len(parts)):
    if i == 0:
        s_start = 0.0
    else:
        s_start = ends[i - 1] + GAP
    if i == len(parts) - 1:
        s_end = ends[i] + tail
    else:
        s_end = ends[i] + GAP
    durs.append(s_end - s_start)
sub_d = durs[-1]

W, H = 1080, 1920
FPS = 30
AMIRI = "/usr/share/fonts/truetype/hosny-amiri/Amiri-Bold.ttf"
if not os.path.exists(AMIRI):
    AMIRI = subprocess.check_output(["fc-match", "-f", "%{file}", "Amiri:bold"]).decode()


def fnt(size):
    return ImageFont.truetype(AMIRI, size)


def grad_bg():
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        k = y / H
        d.line((0, y, W, y), fill=(int(14 + 60 * k), int(18 + 10 * k), int(52 + 80 * k)))
    return img


def draw_text_center(d, txt, y, size, fill):
    f = fnt(size)
    w = d.textlength(txt, font=f)
    d.text(((W - w) / 2, y), txt, font=f, fill=fill, stroke_width=3, stroke_fill=(0, 0, 0))


def make_bell(angle_deg):
    im = Image.new("RGBA", (600, 440), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    white = (255, 255, 255, 255)
    d.ellipse((200, 70, 400, 270), fill=white)
    d.polygon([(200, 170), (400, 170), (435, 290), (165, 290)], fill=white)
    d.rounded_rectangle((155, 280, 445, 325), 22, fill=white)
    d.ellipse((265, 335, 335, 390), fill=white)
    d.ellipse((280, 40, 320, 80), fill=white)
    im = im.rotate(angle_deg, center=(300, 60), resample=Image.BICUBIC)
    return im.resize((120, 88), Image.LANCZOS)


def make_hand():
    im = Image.new("RGBA", (400, 560), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    skin = (255, 206, 158, 255)
    shade = (214, 160, 115, 255)
    sleeve = (245, 245, 250, 255)
    d.rounded_rectangle((100, 270, 340, 500), 70, fill=skin)
    d.rounded_rectangle((115, 20, 195, 320), 40, fill=skin)
    d.rounded_rectangle((195, 245, 245, 315), 24, fill=skin)
    d.rounded_rectangle((245, 255, 295, 325), 24, fill=skin)
    d.rounded_rectangle((295, 270, 340, 335), 22, fill=skin)
    d.rounded_rectangle((55, 330, 140, 430), 38, fill=skin)
    d.line((195, 262, 195, 315), fill=shade, width=5)
    d.line((245, 272, 245, 322), fill=shade, width=5)
    d.line((295, 285, 295, 330), fill=shade, width=5)
    d.rounded_rectangle((105, 480, 325, 560), 20, fill=sleeve)
    return im.resize((180, 252), Image.LANCZOS)


HAND = make_hand()
HAND_TIP = (80, 10)
ROW_Y = 1050
SUB_CX = 400
BELL_CX = 780


def ease(k):
    k = max(0.0, min(1.0, k))
    return k * k * (3 - 2 * k)


def lerp(a, b, k):
    return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)


def pill(d, cx, cy, w, h, fill):
    d.rounded_rectangle((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), int(h / 2), fill=fill)


def frame(tsec, base):
    img = base.copy()
    d = ImageDraw.Draw(img)
    draw_text_center(d, "لا تنسَ دعمنا", 330, 105, (255, 255, 255))
    draw_text_center(d, "بالاشتراك والجرس", 460, 105, (255, 205, 60))

    C = 4.0
    p = tsec % C
    start = (990, 1450)
    A = (SUB_CX + 40, ROW_Y + 45)
    B = (BELL_CX, ROW_Y + 45)
    if p < 0.9:
        pos, press = lerp(start, A, ease(p / 0.9)), 0.0
    elif p < 1.3:
        pos, press = A, math.sin(math.pi * (p - 0.9) / 0.4)
    elif p < 2.1:
        pos, press = lerp(A, B, ease((p - 1.3) / 0.8)), 0.0
    elif p < 2.5:
        pos, press = B, math.sin(math.pi * (p - 2.1) / 0.4)
    elif p < 3.3:
        pos, press = lerp(B, start, ease((p - 2.5) / 0.8)), 0.0
    else:
        pos, press = start, 0.0

    subscribed = p >= 1.1
    sub_press = press if 0.9 <= p < 1.3 else 0.0
    bell_press = press if 2.1 <= p < 2.5 else 0.0

    k = 1 - 0.06 * sub_press
    if subscribed:
        pill(d, SUB_CX, ROW_Y, 520 * k, 140 * k, (70, 70, 78))
        label = "مشترك"
    else:
        pill(d, SUB_CX, ROW_Y, 520 * k, 140 * k, (255, 0, 0))
        label = "اشترك"
    f = fnt(88)
    lw = d.textlength(label, font=f)
    d.text((SUB_CX - lw / 2, ROW_Y - 62), label, font=f, fill=(255, 255, 255))

    kb = 1 - 0.06 * bell_press
    pill(d, BELL_CX, ROW_Y, 180 * kb, 140 * kb, (39, 39, 44))
    bt = p - 2.2
    ang = 28 * math.exp(-2.2 * bt) * math.sin(bt * 20) if bt >= 0 else 0
    bell = make_bell(ang)
    img.paste(bell, (int(BELL_CX - 60), int(ROW_Y - 43)), bell)

    sc = 1 - 0.08 * press
    hw, hh = int(HAND.width * sc), int(HAND.height * sc)
    hand = HAND.resize((hw, hh), Image.LANCZOS)
    img.paste(hand, (int(pos[0] - HAND_TIP[0] * sc), int(pos[1] - HAND_TIP[1] * sc)), hand)

    d = ImageDraw.Draw(img)
    draw_text_center(d, "شكرًا لمتابعتك", 1560, 80, (255, 255, 255))
    return img


os.makedirs("frames", exist_ok=True)
base = grad_bg()
nframes = int(sub_d * FPS) + 1
for k in range(nframes):
    frame(k / FPS, base).save("frames/f%04d.png" % k, compress_level=1)
run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", "frames/f%04d.png", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "22", "-t", "%.3f" % sub_d, "sub_screen.mp4"])

ass = [
    "[Script Info]",
    "ScriptType: v4.00+",
    "PlayResX: 1080",
    "PlayResY: 1920",
    "WrapStyle: 2",
    "",
    "[V4+ Styles]",
    "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
    "Style: Default,%s,115,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,8,3,2,60,60,500,1" % FONT,
    "Style: Hook,%s,125,&H0000E0FF,&H0000E0FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,9,3,8,60,60,260,1" % FONT,
    "",
    "[Events]",
    "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
]

vlist = []
for i, (p, kind) in enumerate(zip(parts, kinds)):
    d = durs[i]
    if kind != "outro":
        clip = "clip%d.mp4" % i
        download(find_video(pq[i], i), clip)
        run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", clip, "-t", "%.3f" % d, "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "sv%d.mp4" % i])
        vlist.append("sv%d.mp4" % i)
    else:
        vlist.append("sub_screen.mp4")

    # captions timed to the measured voice of this sentence
    ws = p.split()
    groups = [" ".join(ws[k:k + 3]) for k in range(0, len(ws), 3)]
    weights = [max(1, len(g.replace(" ", ""))) for g in groups]
    total_w = float(sum(weights))
    gt = starts[i]
    for g, w in zip(groups, weights):
        gd = seg_dur[i] * w / total_w
        ass.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (ts(gt), ts(gt + gd), g))
        gt += gd

hook = clean(ai.get("hook"))
if hook:
    ass.append("Dialogue: 1,%s,%s,Hook,,0,0,0,,%s" % (ts(0), ts(3.0), hook))

with open("subs.ass", "w", encoding="utf-8") as f:
    f.write("\n".join(ass))

with open("vlist.txt", "w") as f:
    for v in vlist:
        f.write("file '%s'\n" % v)

run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "vlist.txt", "-c", "copy", "joined.mp4"])
run(["ffmpeg", "-y", "-i", "joined.mp4", "-i", "voice.wav", "-vf", "subtitles=subs.ass:fontsdir=/usr/share/fonts", "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", "-shortest", "output/video.mp4"])

with open("output/meta.json", "w", encoding="utf-8") as f:
    json.dump({"title": ai.get("title"), "description": ai.get("description"), "tags": ai.get("tags"), "topic": ai.get("topic")}, f, ensure_ascii=False)
print("DONE")