import requests
import time
import csv
import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

load_dotenv()

# ---------------- CONFIG ----------------
REFRESH_TOKEN = os.getenv("YOUR_REFRESH_TOKEN")
ORG_ID = os.getenv("ORG_ID")

TIMEZONE = "America/Toronto"
TOKEN_FILE = "hubstaff_token.json"

MAX_RANGE_DAYS = 7


# ---------------- CLI INPUT ----------------
if len(sys.argv) < 3:
    print("Usage: python hubstaff_daily_summary_cli.py START_DATE END_DATE [csv|json]")
    print("Example: python hubstaff_daily_summary_cli.py 2025-10-01 2025-12-31 csv")
    sys.exit(1)

START_DATE = sys.argv[1]
END_DATE = sys.argv[2]
EXPORT_FORMAT = sys.argv[3] if len(sys.argv) > 3 else "csv"


# ---------------- HELPER ----------------
def seconds_to_hms(seconds):

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    return f"{int(hours):02}:{int(minutes):02}:{int(secs):02}"


# ---------------- TOKEN ----------------
def get_access_token():

    if os.path.exists(TOKEN_FILE):

        with open(TOKEN_FILE, "r") as f:
            token_data = json.load(f)

        expires_at = datetime.fromisoformat(token_data["expires_at"])

        if datetime.utcnow() < expires_at:
            return token_data["access_token"]

    new_token, expires_in = refresh_access_token(REFRESH_TOKEN)

    expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 60)

    token_data = {
        "access_token": new_token,
        "expires_at": expires_at.isoformat()
    }

    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)

    return new_token


def refresh_access_token(refresh_token):

    url = "https://account.hubstaff.com/access_tokens"

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }

    r = requests.post(url, headers=headers, data=data)

    if r.status_code != 200:
        raise Exception(r.text)

    tokens = r.json()

    return tokens["access_token"], tokens["expires_in"]


# ---------------- FETCH ----------------
def fetch_activities(access_token, start, stop):

    base_url = f"https://api.hubstaff.com/v2/organizations/{ORG_ID}/activities"

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    params = {
        "time_slot[start]": start,
        "time_slot[stop]": stop,
        "page_limit": 500
    }

    all_activities = []
    page_start_id = None

    while True:

        if page_start_id:
            params["page_start_id"] = page_start_id

        r = requests.get(base_url, headers=headers, params=params)

        if r.status_code != 200:
            raise Exception(r.text)

        data = r.json()

        activities = data.get("activities", [])
        all_activities.extend(activities)

        pagination = data.get("pagination", {})
        page_start_id = pagination.get("next_page_start_id")

        if not page_start_id:
            break

        time.sleep(0.3)

    return all_activities


# ---------------- SUMMARY ----------------
def generate_daily_summary(access_token):

    tz = ZoneInfo(TIMEZONE)

    start = datetime.strptime(START_DATE, "%Y-%m-%d")
    end = datetime.strptime(END_DATE, "%Y-%m-%d")

    daily_seconds = defaultdict(int)
    daily_keyboard = defaultdict(int)
    daily_mouse = defaultdict(int)

    current = start

    while current <= end:

        window_end = min(current + timedelta(days=MAX_RANGE_DAYS), end + timedelta(days=1))

        start_ts = datetime.combine(current, datetime.min.time(), tz)
        stop_ts = datetime.combine(window_end, datetime.min.time(), tz)

        print(f"Fetching {start_ts} → {stop_ts}")

        activities = fetch_activities(
            access_token,
            start_ts.isoformat(),
            stop_ts.isoformat()
        )

        for a in activities:

            tracked = a.get("tracked", 0)
            keyboard = a.get("keyboard", 0)
            mouse = a.get("mouse", 0)

            if tracked == 0:
                continue

            ts = a.get("starts_at") or a.get("created_at")

            if not ts:
                continue

            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tz)

            day = dt.date().isoformat()

            daily_seconds[day] += tracked
            daily_keyboard[day] += keyboard
            daily_mouse[day] += mouse

        current = window_end

    results = []

    d = start

    while d <= end:

        day = d.date().isoformat()

        sec = daily_seconds[day]
        hrs = round(sec / 3600, 2)
        hms = seconds_to_hms(sec)

        kb = daily_keyboard[day]
        ms = daily_mouse[day]

        activity = 0

        if sec > 0:
            activity = round(((kb + ms) / sec) * 100, 2)

        results.append({
            "date": day,
            "tracked_hours": hrs,
            "tracked_time": hms,
            "activity_percent": activity
        })

        d += timedelta(days=1)

    return results


# ---------------- EXPORT ----------------
def export(results):

    if EXPORT_FORMAT.lower() == "json":

        with open("hubstaff_daily_summary.json", "w") as f:
            json.dump(results, f, indent=2)

        print("JSON exported")

    else:

        with open("hubstaff_daily_summary.csv", "w", newline="") as f:

            writer = csv.writer(f)

            writer.writerow([
                "date",
                "tracked_hours",
                "tracked_time",
                "activity_percent"
            ])

            for r in results:
                writer.writerow([
                    r["date"],
                    r["tracked_hours"],
                    r["tracked_time"],
                    r["activity_percent"]
                ])

        print("CSV exported")


# ---------------- MAIN ----------------
if __name__ == "__main__":

    token = get_access_token()

    summary = generate_daily_summary(token)

    export(summary)

    print("\nDaily Summary")

    for r in summary:
        print(
            r["date"],
            r["tracked_time"],
            "|",
            r["tracked_hours"],
            "hrs | activity:",
            r["activity_percent"],
            "%"
        )
