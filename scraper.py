import os
import requests
import json
from datetime import datetime, timedelta, UTC
from typing import List, Optional

def load_env():
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                key, value = line.strip().split("=", 1)
                os.environ[key] = value

load_env()

def get_env(key: str, default=None):
    envVar = os.getenv(key)
    if envVar is None or envVar == "":
        return default
    return envVar

def get_required_env(key: str):
    envVar = os.getenv(key)
    if envVar is None or envVar == "":
        raise ValueError(f"Environment variable {key} is required.")
    return envVar

SCRAPING_ENABLED = get_env("SCRAPING_ENABLED", "1") == "1" # Default to True (1)
SERVICE_ID = get_env("SERVICE_ID", "8029") # 8029 is for tennis, 8033 is for basketball
CHECK_DAYS_AHEAD = get_env("CHECK_DAYS_AHEAD") # e.g., "3"
CHECK_SPECIFIC_DAYS = get_env("CHECK_SPECIFIC_DAYS") # e.g., "2025-04-10,2025-04-12" ISO format: YYYY-MM-DD
TIME_INTERVAL_START = get_env("TIME_INTERVAL_START", "08:00") # default 16:00 (24hr format)
TIME_INTERVAL_END = get_env("TIME_INTERVAL_END", "22:00") # default 20:00 (24hr format)

CLIENT_SESSION = get_required_env("CLIENT_SESSION") # long-lived cookie
CALENDIS_USER_EMAIL = get_required_env("CALENDIS_USER_EMAIL") # email used to login to calendis.ro
CALENDIS_USER_PASSWORD = get_required_env("CALENDIS_USER_PASSWORD") # password used to login to calendis.ro
GH_PAT_TOKEN = get_required_env("GH_PAT_TOKEN") # GitHub Personal Access Token (PAT) for updating environment variables

TELEGRAM_TOKEN = get_required_env("TELEGRAM_TOKEN") # Telegram bot token
TELEGRAM_CHAT_ID = get_required_env("TELEGRAM_CHAT_ID") # Telegram chat ID

# API URL template
API_URL_TEMPLATE = "https://www.calendis.ro/api/get_available_slots"
LOCATION_ID = "1651"  # Baza Sportiva location ID

# term dictionary for the service by service id
SERVICE_TERMS = {
    "8029": "Tennis",
    "8033": "Basketball",
}

def parse_time_str(time_str: str) -> datetime.time:
    """Convert a 'HH:MM' string to a time object."""
    return datetime.strptime(time_str, "%H:%M").time()

def get_dates_to_check() -> List[int]:
    """
    Determine which days to check.
    Returns a list of Unix timestamps (for the beginning of the day in UTC)
    """
    dates = []
    if CHECK_SPECIFIC_DAYS:
        # Expecting a comma separated list of dates in ISO format (YYYY-MM-DD)
        for date_str in CHECK_SPECIFIC_DAYS.split(","):
            try:
                date_obj = datetime.strptime(date_str.strip(), "%Y-%m-%d")
                # Convert to Unix timestamp (assuming 00:00 of that day in UTC)
                dates.append(int(date_obj.timestamp()))
            except ValueError:
                print(f"Invalid date format for {date_str}. Use YYYY-MM-DD.")
    elif CHECK_DAYS_AHEAD:
        try:
            days_ahead = int(CHECK_DAYS_AHEAD)
            today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            for i in range(days_ahead):
                date_obj = today + timedelta(days=i)
                dates.append(int(date_obj.timestamp()))
        except ValueError:
            print("CHECK_DAYS_AHEAD must be an integer.")
    else:
        # Default: check just today
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        dates.append(int(today.timestamp()))
    return dates

def is_slot_in_time_interval(slot_timestamp: int) -> bool:
    """
    Check if the slot (given by its Unix timestamp) falls within the configured time interval.
    Assumes the timestamp is in UTC; adjust if needed.
    """
    slot_time = datetime.fromtimestamp(slot_timestamp, UTC).time()
    start_time = parse_time_str(TIME_INTERVAL_START)
    end_time = parse_time_str(TIME_INTERVAL_END)
    return start_time <= slot_time <= end_time

def send_telegram_notification(message: str) -> None:
    """
    Send a message via Telegram using the Bot API.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram notification not configured.")
        return

    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        response = requests.post(telegram_url, data=payload)
        if response.status_code != 200:
            print(f"Failed to send Telegram message: {response.text}")
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

def login_to_calendis() -> str:
    """
    Login to Calendis and return the new client_session cookie.
    """
    login_url = "https://www.calendis.ro/api/login"
    payload = {
        "email": CALENDIS_USER_EMAIL,
        "password": CALENDIS_USER_PASSWORD,
        "remember": False
    }
    headers = {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Host": "www.calendis.ro",
        "Content-Type": "application/json",
        "Origin": "https://www.calendis.ro",
        "Referer": "https://www.calendis.ro/login",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"'
    }
    
    try:
        response = requests.post(login_url, json=payload, headers=headers)
        response.raise_for_status()
        
        # Extract client_session from cookies
        cookies = response.cookies
        client_session = cookies.get("client_session")
        
        if not client_session:
            # If not in cookies, check response body
            response_data = response.json()
            if response_data.get("success") == 1:
                # Check in Set-Cookie header
                set_cookie_header = response.headers.get("Set-Cookie", "")
                if "client_session=" in set_cookie_header:
                    client_session = set_cookie_header.split("client_session=")[1].split(";")[0]
        
        if not client_session:
            raise Exception("Failed to get client_session from login response")
            
        print("Successfully logged in and obtained new client_session")
        return client_session
        
    except Exception as e:
        print(f"Login failed: {e}")
        raise

def update_github_env_variable(variable_name, value):
    """
    Updates a GitHub environment variable using GitHub API.
    This requires a PAT (Personal Access Token) with appropriate permissions.
    """
    print(f"Updating GitHub environment variable '{variable_name}' to '{value}'")
    
    repo_owner = "boicualexandru" 
    repo_name = "scraping-calendis"
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/variables/{variable_name}"
    headers = {
        "Authorization": f"Bearer {GH_PAT_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    data = {"value": value}
    response = requests.patch(url, json=data, headers=headers)
    response.raise_for_status()

def check_slots_for_date(date_unix: int) -> Optional[List[dict]]:
    """
    Check available slots for a given day (by Unix timestamp).
    Returns a list of available slots that fall in the desired time interval,
    or None if the API call indicates no available slots.
    """
    global CLIENT_SESSION  # Allow modifying the global variable
    
    params = {
        "service_id": SERVICE_ID,
        "location_id": LOCATION_ID,
        "date": date_unix,
        "day_only": "1"
    }
    headers = {
        "Cookie": f"cookie_message=0; client_session={CLIENT_SESSION}",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Host": "www.calendis.ro",
        "Referer": "https://www.calendis.ro/cluj-napoca/baza-sportiva-gheorgheni/tenis/s",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"'
    }
    
    try:
        response = requests.get(API_URL_TEMPLATE, params=params, headers=headers)
        
        # Check if we need to login due to expired session
        # Handle both 401 and 500 status codes, and also check response text for auth errors
        if response.status_code in [401, 500] or "auth_error" in response.text.lower():
            print(f"Session may have expired (status code: {response.status_code}). Attempting to login and get new session...")
            CLIENT_SESSION = login_to_calendis()
            
            # Update headers with new session and retry
            headers["Cookie"] = f"cookie_message=0; client_session={CLIENT_SESSION}"
            response = requests.get(API_URL_TEMPLATE, params=params, headers=headers)
            
            # Notify about session update - useful for updating GitHub env var
            update_github_env_variable("CLIENT_SESSION", CLIENT_SESSION)
        
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Error fetching data for {date_unix}: {e}")
        raise

    if data.get("success") != 1:
        print(f"No available slots on {datetime.fromtimestamp(date_unix, UTC).date()}")
        return None

    # Filter slots within the desired time interval
    slots = data.get("available_slots", [])
    filtered_slots = [slot for slot in slots if is_slot_in_time_interval(slot["time"]) and slot.get("is_available") == 1]
    
    return filtered_slots if filtered_slots else None

def main():
    if not SCRAPING_ENABLED:
        print("Scraping is disabled. Exiting.")
        return

    dates_to_check = get_dates_to_check()

    all_slots = {}
    for date_unix in dates_to_check:
        date_str = datetime.fromtimestamp(date_unix, UTC).strftime("%Y-%m-%d")
        slots = check_slots_for_date(date_unix)
        if slots:
            all_slots[date_str] = slots
    
    if not all_slots:
        print("No matching slots found in the desired time interval, so no notification will be sent.")
        return
    
    message = f"Available slots for {SERVICE_TERMS.get(SERVICE_ID, 'Unknown Service')}:\n"
    for date_str, slots in all_slots.items():
        message += f"\n{date_str}:\n"
        for slot in slots:
            slot_time_str = datetime.fromtimestamp(slot["time"], UTC).strftime("%H:%M")
            message += f" - {slot_time_str}\n"
    message += f"\nChecked time interval: {TIME_INTERVAL_START} - {TIME_INTERVAL_END}\n"
    if CHECK_DAYS_AHEAD:
        message += f"Checked {CHECK_DAYS_AHEAD} days ahead.\n"
    if CHECK_SPECIFIC_DAYS:
        message += f"Checked specific days: {CHECK_SPECIFIC_DAYS}\n"

    print(f"Sending notification...\n{message}")
    send_telegram_notification(message)
    # disable scraping after sending notification
    update_github_env_variable("SCRAPING_ENABLED", "0")

if __name__ == "__main__":
    main()
