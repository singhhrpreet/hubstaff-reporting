import requests
import time
import csv
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ------------------ CONFIG ------------------
REFRESH_TOKEN = os.getenv("YOUR_REFRESH_TOKEN")
ORG_ID = os.getenv("ORG_ID")
START_DATE = "2025-11-14T00:00:00Z"
STOP_DATE  = "2025-11-21T00:00:00Z" # Accepts 7 day max range
TOKEN_FILE = "hubstaff_token.json"  # Local cache for access token

# ------------------ STEP 1: Load or refresh access token ------------------
def get_access_token():
    """
    Loads access token from cache if valid, otherwise refreshes it using refresh_token.
    """
    # Try loading existing token file
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token_data = json.load(f)
            expires_at = datetime.fromisoformat(token_data["expires_at"])
            if datetime.utcnow() < expires_at:
                print("✅ Using cached access token.")
                return token_data["access_token"]

            print("⚠️ Cached token expired, refreshing...")

    # Refresh the token if no valid cache
    new_token, new_refresh, expires_in = refresh_access_token(REFRESH_TOKEN)

    # Save new token to file
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 60)  # small buffer
    token_data = {
        "access_token": new_token,
        "expires_at": expires_at.isoformat(),
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)
    print("💾 New access token saved to file.")
    return new_token

def refresh_access_token(refresh_token):
    """
    Calls Hubstaff API to get a new access token from refresh token.
    """
    url = "https://account.hubstaff.com/access_tokens"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }

    response = requests.post(url, headers=headers, data=data)
    if response.status_code != 200:
        raise Exception(f"Failed to refresh token: {response.status_code} {response.text}")
    tokens = response.json()
    print("✅ Access token refreshed.")
    return tokens["access_token"], tokens["refresh_token"], tokens["expires_in"]

# ------------------ STEP 2: Fetch all activities ------------------
def fetch_activities(access_token, org_id, start, stop):
    base_url = f"https://api.hubstaff.com/v2/organizations/{org_id}/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
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

        response = requests.get(base_url, headers=headers, params=params)
        if response.status_code != 200:
            raise Exception(f"API Error: {response.status_code} {response.text}")

        data = response.json()
        activities = data.get("activities", [])
        all_activities.extend(activities)

        # Pagination
        pagination = data.get("pagination", {})
        page_start_id = pagination.get("next_page_start_id")
        if not page_start_id:
            break

        print(f"➡️  Fetched {len(activities)} activities, continuing with page_start_id={page_start_id}")
        time.sleep(0.4)  # respect rate limits

    print(f"✅ Total activities fetched: {len(all_activities)}")
    return all_activities

# ------------------ STEP 3: Summarize by client ------------------
def summarize_by_client(activities):
    summary = {}

    for a in activities:
        client = a.get("client", "unknown")
        if client not in summary:
            summary[client] = {
                "tracked": 0,
                "keyboard": 0,
                "mouse": 0,
                "input_tracked": 0
            }

        summary[client]["tracked"] += a.get("tracked", 0)
        summary[client]["keyboard"] += a.get("keyboard", 0)
        summary[client]["mouse"] += a.get("mouse", 0)
        summary[client]["input_tracked"] += a.get("input_tracked", 0)

    # Convert to hours for readability
    for client in summary:
        summary[client]["tracked_hours"] = round(summary[client]["tracked"] / 3600, 2)

    return summary

# ------------------ STEP 4: Export to CSV ------------------
def export_to_csv(summary):
    with open("hubstaff_summary_by_client.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["client", "tracked_seconds", "tracked_hours", "keyboard", "mouse", "input_tracked"])
        for client, stats in summary.items():
            writer.writerow([
                client,
                stats["tracked"],
                stats["tracked_hours"],
                stats["keyboard"],
                stats["mouse"],
                stats["input_tracked"]
            ])
    print("✅ Exported summary to hubstaff_summary_by_client.csv")

# ------------------ MAIN ------------------
if __name__ == "__main__":
    access_token = get_access_token()
    activities = fetch_activities(access_token, ORG_ID, START_DATE, STOP_DATE)
    summary = summarize_by_client(activities)
    export_to_csv(summary)

    print("\n=== Summary by Client ===")
    for client, stats in summary.items():
        print(f"{client}: {stats['tracked_hours']} hrs (tracked_seconds={stats['tracked']})")
