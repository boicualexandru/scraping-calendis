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

SCRAPING_ENABLED = os.getenv("SCRAPING_ENABLED", "1") == "1" # Default to True (1)
SERVICE_ID = os.getenv("SERVICE_ID", "8029") # 8029 is for tennis, 8033 is for basketball
CHECK_DAYS_AHEAD = os.getenv("CHECK_DAYS_AHEAD") # e.g., "3"
CHECK_SPECIFIC_DAYS = os.getenv("CHECK_SPECIFIC_DAYS") # e.g., "2025-04-10,2025-04-12" ISO format: YYYY-MM-DD
TIME_INTERVAL_START = os.getenv("TIME_INTERVAL_START", "08:00") # default 16:00 (24hr format)
TIME_INTERVAL_END = os.getenv("TIME_INTERVAL_END", "20:00") # default 20:00 (24hr format)

CLIENT_SESSION = os.getenv("CLIENT_SESSION") # long-lived cookie
if not CLIENT_SESSION:
    raise ValueError("CLIENT_SESSION must be set in the environment variables.")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") # Telegram bot token
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN must be set in the environment variables.")

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") # Telegram chat ID
if not TELEGRAM_CHAT_ID:
    raise ValueError("TELEGRAM_CHAT_ID must be set in the environment variables.")

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

def check_slots_for_date(date_unix: int) -> Optional[List[dict]]:
    """
    Check available slots for a given day (by Unix timestamp).
    Returns a list of available slots that fall in the desired time interval,
    or None if the API call indicates no available slots.
    """
    params = {
        "service_id": SERVICE_ID,
        "location_id": LOCATION_ID,
        "date": date_unix,
        "day_only": "1"
    }
    headers = {
        "Cookie": f"cookie_message=0; client_session={CLIENT_SESSION}"
    }
    
    try:
        response = requests.get(API_URL_TEMPLATE, params=params, headers=headers)
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
    overall_message = f"Available slots for {SERVICE_TERMS.get(SERVICE_ID, 'Unknown Service')}:\n"
    
    for date_unix in dates_to_check:
        date_str = datetime.fromtimestamp(date_unix, UTC).strftime("%Y-%m-%d")
        slots = check_slots_for_date(date_unix)
        if slots:
            overall_message += f"Slots available on {date_str}:\n"
            for slot in slots:
                slot_time_str = datetime.fromtimestamp(slot["time"], UTC).strftime("%H:%M")
                overall_message += f" - {slot_time_str} (staff: {slot.get('staff_id')})\n"
        else:
            print(f"No matching slots for {date_str} in the desired time interval.")
    
    overall_message += f"\nChecked time interval: {TIME_INTERVAL_START} - {TIME_INTERVAL_END}\n"
    if CHECK_DAYS_AHEAD:
        overall_message += f"Checked {CHECK_DAYS_AHEAD} days ahead.\n"
    if CHECK_SPECIFIC_DAYS:
        overall_message += f"Checked specific days: {CHECK_SPECIFIC_DAYS}\n"

    if overall_message:
        print("Sending notification...")
        send_telegram_notification(overall_message)
    else:
        print("No slots available in the specified interval for any checked day.")

if __name__ == "__main__":
    main()
