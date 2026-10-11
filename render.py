import json, os, re, subprocess, urllib.request, urllib.parse

data = json.loads(os.environ["PAYLOAD"])
ai = data["ai"]
fallback_videos = data.get("videos", [])
content = ai["scenes"]
PIX = os.environ.get("PIXABAY_KEY", "")
subject = (ai.get("subject_en") or "").strip()
VOICE = "ar-EG-ShakirNeural"
FONT = "Amiri"
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


# full timeline: intro + content + outro
items = []
intro = clean(ai.get("intro"))
if intro:
    items.append({"kind": "intro", "text": intro, "q": ""})
for s in content:
    n = clean(s.get("narration"))
    if n:
        items.append({"kind": "content", "text": n, "q": s.get("search_query", "")})
outro = clean(ai.get("outro")) or "اشترك في القناة واضغط على الجرس للمزيد"
items.append({"kind": "outro", "text": outro, "q": ""})

hook = clean(ai.get("hook"))

ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080",
       "PlayResY: 1920", "WrapStyle: 2", "",
       "[V4+ Styles]",
       "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
       "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,"
       "ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
       "MarginL,MarginR,MarginV,Encoding",
       "Style: Default,%s,120,&H00FFFFFF,&H00FFFFFF,"
       "&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,8,3,2,50,50,500,1" % FONT,
       "Style: Hook,%s,130,&H0000E0FF,&H0000E0FF,"
       "&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,9,3,8,50,50,260,1" % FONT,
       "Style: Sub,%s,125,&H0000A5FF,&H0000A5FF,"
       "&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,9,3,2,50,50,500,1" % FONT,
       "Style: Tag,%s,95,&H00FFFFFF,&H00FFFFFF,"
       "&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,7,3,8,50,50,420,1" % FONT,
       "", "[Events]",
       "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]

t = 0.0
ci = 0
for i, it in enumerate(items):
    with open("n%d.txt" % i, "w", encoding="utf-8") as f:
        f.write(it["text"])
    run(["edge-tts", "--voice", VOICE, "--rate=-4%",
         "--file", "n%d.txt" % i, "--write-media", "a%d.mp3" % i])
    d = duration("a%d.mp3" % i) + 0.3
    run(["ffmpeg", "-y", "-i", "a%d.mp3" % i,
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,apad",
         "-t", "%.3f" % d, "-ar", "44100", "-ac", "2", "sa%d.wav" % i])

    clip = "clip%d.mp4" % i
    q = it["q"] or ("subscribe" if it["kind"] == "outro" else "")
    download(find_video(q, i), clip)
    run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", clip,
         "-t", "%.3f" % d,
         "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,setsar=1,fps=30",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", "sv%d.mp4" % i])

    style = "Sub" if it["kind"] == "outro" else "Default"
    ws = it["text"].split()
    groups = [" ".join(ws[k:k + 3]) for k in range(0, len(ws), 3)]
    weights = [max(1, len(g)) for g in groups]
    speak = d - 0.3
    gt = t
    for g, w in zip(groups, weights):
        gd = speak * w / sum(weights)
        ass.append("Dialogue: 0,%s,%s,%s,,0,0,0,,%s" % (ts(gt), ts(gt + gd), style, g))
        gt += gd
    if it["kind"] == "outro":
        ass.append("Dialogue: 1,%s,%s,Tag,,0,0,0,,%s" % (
            ts(t), ts(t + d), "اشترك  \u2022  فعّل الجرس  \u2022  شاركنا"))
    t += d

if hook:
    ass.append("Dialogue: 1,%s,%s,Hook,,0,0,0,,%s" % (ts(0), ts(3.0), hook))

with open("subs.ass", "w", encoding="utf-8") as f:
    f.write("\n".join(ass))

with open("vlist.txt", "w") as f:
    for i in range(len(items)):
        f.write("file 'sv%d.mp4'\n" % i)
with open("alist.txt", "w") as f:
    for i in range(len(items)):
        f.write("file 'sa%d.wav'\n" % i)

run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "vlist.txt",
     "-c", "copy", "joined.mp4"])
run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "alist.txt",
     "-c", "copy", "voice.wav"])
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
