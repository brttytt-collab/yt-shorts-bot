import json, os, subprocess, urllib.request, urllib.parse

data = json.loads(os.environ["PAYLOAD"])
ai = data["ai"]
fallback_videos = data.get("videos", [])
scenes = ai["scenes"]
PIX = os.environ.get("PIXABAY_KEY", "")
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


used = set()


def find_video(query, i):
    if PIX and query:
        try:
            url = ("https://pixabay.com/api/videos/?key=" + PIX
                   + "&per_page=10&q=" + urllib.parse.quote(query))
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                hits = json.loads(r.read().decode())["hits"]
            for h in hits:
                v = h["videos"]
                u = (v.get("large") or {}).get("url") or (v.get("medium") or {}).get("url")
                if u and u not in used:
                    used.add(u)
                    return u
        except Exception as e:
            print("pixabay search failed:", e)
    if fallback_videos:
        return fallback_videos[i % len(fallback_videos)]
    raise SystemExit("no video available")


# narration per scene (fallback: split the full script evenly)
narrs = [s.get("narration") for s in scenes]
if not all(narrs):
    words = (ai.get("script") or " ".join(s.get("caption", "") for s in scenes)).split()
    n = len(scenes)
    size = max(1, len(words) // n + 1)
    narrs = [" ".join(words[k * size:(k + 1) * size]) or "." for k in range(n)]

# captions style: big, bold, centered lower third
ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080",
       "PlayResY: 1920", "WrapStyle: 2", "",
       "[V4+ Styles]",
       "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
       "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,"
       "ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
       "MarginL,MarginR,MarginV,Encoding",
       "Style: Default,Noto Sans Arabic,110,&H00FFFFFF,&H00FFFFFF,"
       "&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,7,2,2,50,50,480,1",
       "", "[Events]",
       "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]

t = 0.0
for i, s in enumerate(scenes):
    narr = narrs[i]
    with open("n%d.txt" % i, "w", encoding="utf-8") as f:
        f.write(narr)
    run(["edge-tts", "--voice", "ar-SA-HamedNeural",
         "--file", "n%d.txt" % i, "--write-media", "a%d.mp3" % i])
    d = duration("a%d.mp3" % i) + 0.25

    # audio segment padded to exactly d
    run(["ffmpeg", "-y", "-i", "a%d.mp3" % i, "-af", "apad",
         "-t", "%.3f" % d, "-ar", "44100", "-ac", "2", "sa%d.wav" % i])

    # video segment exactly d
    clip = "clip%d.mp4" % i
    download(find_video(s.get("search_query", ""), i), clip)
    run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", clip,
         "-t", "%.3f" % d,
         "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,setsar=1,fps=30",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", "sv%d.mp4" % i])

    # captions: groups of 3 words, timed by text length inside the voice
    ws = narr.split()
    groups = [" ".join(ws[k:k + 3]) for k in range(0, len(ws), 3)]
    weights = [max(1, len(g)) for g in groups]
    speak = d - 0.25
    gt = t
    for g, w in zip(groups, weights):
        gd = speak * w / sum(weights)
        ass.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (ts(gt), ts(gt + gd), g))
        gt += gd
    t += d

with open("subs.ass", "w", encoding="utf-8") as f:
    f.write("\n".join(ass))

with open("vlist.txt", "w") as f:
    for i in range(len(scenes)):
        f.write("file 'sv%d.mp4'\n" % i)
with open("alist.txt", "w") as f:
    for i in range(len(scenes)):
        f.write("file 'sa%d.wav'\n" % i)

run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "vlist.txt",
     "-c", "copy", "joined.mp4"])
run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "alist.txt",
     "-c", "copy", "voice.wav"])
run(["ffmpeg", "-y", "-i", "joined.mp4", "-i", "voice.wav",
     "-vf", "subtitles=subs.ass",
     "-map", "0:v", "-map", "1:a",
     "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
     "-c:a", "aac", "-shortest", "output/video.mp4"])

with open("output/meta.json", "w", encoding="utf-8") as f:
    json.dump({"title": ai.get("title"), "description": ai.get("description"),
               "tags": ai.get("tags")}, f, ensure_ascii=False)
print("DONE")
