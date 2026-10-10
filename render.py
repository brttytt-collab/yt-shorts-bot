import json, os, subprocess, urllib.request

data = json.loads(os.environ["PAYLOAD"])
ai = data["ai"]
videos = data["videos"]
scenes = ai["scenes"]
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


# 1) voice
caps = [s.get("caption", "") for s in scenes]
text = ai.get("script") or ai.get("narration") or ". ".join(caps)
with open("voice.txt", "w", encoding="utf-8") as f:
    f.write(text)
run(["edge-tts", "--voice", "ar-SA-HamedNeural",
     "--file", "voice.txt", "--write-media", "voice.mp3"])
total = duration("voice.mp3") + 0.5

# 2) scene durations scaled to the voice length
weights = [max(1, float(s["end"]) - float(s["start"])) for s in scenes]
durs = [total * w / sum(weights) for w in weights]

# 3) clips
for i, d in enumerate(durs):
    clip = "clip%d.mp4" % i
    download(videos[i % len(videos)], clip)
    run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", clip,
         "-t", "%.2f" % d,
         "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,setsar=1,fps=30",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", "seg%d.mp4" % i])

with open("list.txt", "w") as f:
    for i in range(len(durs)):
        f.write("file 'seg%d.mp4'\n" % i)
run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
     "-c", "copy", "joined.mp4"])

# 4) captions (ASS, handles Arabic shaping)
ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080",
       "PlayResY: 1920", "",
       "[V4+ Styles]",
       "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
       "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,"
       "ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
       "MarginL,MarginR,MarginV,Encoding",
       "Style: Default,Noto Sans Arabic,72,&H00FFFFFF,&H00FFFFFF,"
       "&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,1,2,60,60,350,1",
       "", "[Events]",
       "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
t = 0.0
for i, d in enumerate(durs):
    ass.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (ts(t), ts(t + d), caps[i]))
    t += d
with open("subs.ass", "w", encoding="utf-8") as f:
    f.write("\n".join(ass))

# 5) final video
run(["ffmpeg", "-y", "-i", "joined.mp4", "-i", "voice.mp3",
     "-vf", "subtitles=subs.ass",
     "-map", "0:v", "-map", "1:a",
     "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
     "-c:a", "aac", "-shortest", "output/video.mp4"])

with open("output/meta.json", "w", encoding="utf-8") as f:
    json.dump({"title": ai.get("title"), "description": ai.get("description"),
               "tags": ai.get("tags")}, f, ensure_ascii=False)
print("DONE")
