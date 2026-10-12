import json, os, urllib.request, urllib.parse

CID = os.environ["YOUTUBE_CLIENT_ID"]
CSEC = os.environ["YOUTUBE_CLIENT_SECRET"]
RTOK = os.environ["YOUTUBE_REFRESH_TOKEN"]
PRIVACY = os.environ.get("PRIVACY", "private")

meta = json.load(open("output/meta.json", encoding="utf-8"))
title = (meta.get("title") or "Short")[:95]
if "#Shorts" not in title:
    title = (title + " #Shorts")[:100]
desc = (meta.get("description") or "") + "\n\n#Shorts"
tags = meta.get("tags") or []

# 1) access token from the refresh token
data = urllib.parse.urlencode({"client_id": CID, "client_secret": CSEC, "refresh_token": RTOK, "grant_type": "refresh_token"}).encode()
with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=60) as r:
    access = json.loads(r.read().decode())["access_token"]

# 2) start a resumable upload
body = json.dumps({
    "snippet": {"title": title, "description": desc, "tags": tags, "categoryId": "24"},
    "status": {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
}).encode("utf-8")
req = urllib.request.Request(
    "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
    data=body,
    headers={"Authorization": "Bearer " + access, "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": "video/mp4"},
)
with urllib.request.urlopen(req, timeout=60) as r:
    upload_url = r.headers["Location"]

# 3) send the video file
video = open("output/video.mp4", "rb").read()
req = urllib.request.Request(upload_url, data=video, method="PUT", headers={"Content-Type": "video/mp4", "Content-Length": str(len(video))})
with urllib.request.urlopen(req, timeout=600) as r:
    res = json.loads(r.read().decode())
print("UPLOADED video id:", res.get("id"))
