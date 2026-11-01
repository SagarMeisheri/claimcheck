"""Seed launch channels by resolving YouTube handles to channel IDs (YouTube Data API).

  YOUTUBE_API_KEY=... SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python scripts/seed_channels.py

Handles are best guesses: the script prints any it can't resolve so you can fix them.
perceived_lean is internal-only (hidden from the public by column grants) and used
for the weekly balance check, not shown per channel.

Rerun monthly: YouTube's API policies limit how long API data (such as avatar URLs) may be kept
without refreshing.
"""

from __future__ import annotations

import os

import httpx

# (handle, display name, track, perceived_lean)
CHANNELS = [
    # Politics: politicians and parliament
    ("@NarendraModi", "Narendra Modi", "politics", "supportive"),
    ("@BJP4India", "BJP", "politics", "supportive"),
    ("@INCIndia", "Indian National Congress", "politics", "critical"),
    ("@RahulGandhi", "Rahul Gandhi", "politics", "critical"),
    ("@AamAadmiParty", "Aam Aadmi Party", "politics", "critical"),
    ("@SansadTV", "Sansad TV", "politics", "neutral"),
    # Politics: TV news
    ("@abpnewstv", "ABP News", "politics", "neutral"),
    ("@IndiaTV", "India TV", "politics", "neutral"),
    ("@zeenews", "Zee News", "politics", "neutral"),
    ("@aajtak", "Aaj Tak", "politics", "neutral"),
    ("@NDTV", "NDTV 24x7", "politics", "neutral"),
    ("@IndiaToday", "India Today", "politics", "neutral"),
    # Politics: digital news and explainers
    ("@TheLallantop", "The Lallantop", "politics", "neutral"),
    ("@ThePrintIndia", "ThePrint", "politics", "neutral"),
    ("@BBCNewsHindi", "BBC News Hindi", "politics", "neutral"),
    ("@MohakMangal", "Mohak Mangal", "politics", "neutral"),
    # Politics: commentators (balanced by side)
    ("@dhruvrathee", "Dhruv Rathee", "politics", "critical"),
    ("@TheDeshBhakt", "The Deshbhakt", "politics", "critical"),
    ("@ravishkumar.official", "Ravish Kumar", "politics", "critical"),
    ("@abhisarsharma", "Abhisar Sharma", "politics", "critical"),
    ("@ajeetbharti", "Ajeet Bharti", "politics", "supportive"),
    ("@SushantBSinha", "Sushant Sinha", "politics", "supportive"),
    ("@ChanakyaDialogues", "The Chanakya Dialogues", "politics", "supportive"),
    ("@TheJaipurDialogues", "The Jaipur Dialogues", "politics", "supportive"),
    # Finance and health
    ("@nikhil.kamath", "WTF is with Nikhil Kamath", "finance_health", "neutral"),
    ("@rajshamani", "Figuring Out (Raj Shamani)", "finance_health", "neutral"),
    ("@AkshatShrivastava", "Akshat Shrivastava", "finance_health", "neutral"),
    ("@LabourLawAdvisor", "Labour Law Advisor", "finance_health", "neutral"),
    ("@ThinkSchool", "Think School", "finance_health", "neutral"),
    ("@foodpharmer", "FoodPharmer", "finance_health", "neutral"),
]


def main() -> None:
    from supabase import create_client

    key = os.environ["YOUTUBE_API_KEY"]
    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    missing = []
    with httpx.Client(timeout=20) as client:
        for handle, name, track, lean in CHANNELS:
            r = client.get("https://www.googleapis.com/youtube/v3/channels",
                           params={"part": "id,snippet", "forHandle": handle, "key": key})
            items = r.json().get("items", []) if r.status_code == 200 else []
            if not items:
                missing.append(handle)
                continue
            thumbs = items[0]["snippet"].get("thumbnails", {})
            avatar = (thumbs.get("default") or thumbs.get("medium") or {}).get("url")
            db.table("channels").upsert({"youtube_channel_id": items[0]["id"], "name": name, "track": track,
                                         "perceived_lean": lean, "avatar_url": avatar},
                                        on_conflict="youtube_channel_id").execute()
            print(f"ok   {handle:28} -> {items[0]['id']}")
    sides = {"supportive": 0, "critical": 0}
    for _, _, track, lean in CHANNELS:
        if track == "politics" and lean in sides:
            sides[lean] += 1
    print(f"\nPolitical commentator/party balance in seed list: {sides}")
    if missing:
        print("Could not resolve (fix the handle and rerun):", ", ".join(missing))


if __name__ == "__main__":
    main()
