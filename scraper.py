import os
import requests
import json
from datetime import datetime, timedelta
from typing import List, Optional

# Configuration from environment variables
SERVICE_ID = os.environ.get("SERVICE_ID", "8029")  # default to tennis
LOCATION_ID = os.environ.get("LOCATION_ID", "1651")  # as in your URL
CLIENT_SESSION = os.environ.get("CLIENT_SESSION")  # your long-lived cookie

# For scraping days:
# Either use CHECK_DAYS_AHEAD (an integer) OR CHECK_SPECIFIC_DAYS (comma separated list, ISO format: YYYY-MM-DD)
CHECK_DAYS_AHEAD = os.environ.get("CHECK_DAYS_AHEAD")  # e.g., "3"
CHECK_SPECIFIC_DAYS = os.environ.get("CHECK_SPECIFIC_DAYS")  # e.g., "2025-04-10,2025-04-12"

# Time interval of interest (24hr format)
TIME_INTERVAL_START = os.environ.get("TIME_INTERVAL_START", "16:00")  # default 16:00
TIME_INTERVAL_END = os.environ.get("TIME_INTERVAL_END", "20:00")      # default 20:00

# Telegram notification configuration
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Scraping enabled flag (allow turning off the script)
SCRAPING_ENABLED = os.environ.get("SCRAPING_ENABLED", "1") == "1"

# API URL template
API_URL_TEMPLATE = "https://www.calendis.ro/api/get_available_slots"

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
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            for i in range(days_ahead):
                date_obj = today + timedelta(days=i)
                dates.append(int(date_obj.timestamp()))
        except ValueError:
            print("CHECK_DAYS_AHEAD must be an integer.")
    else:
        # Default: check just today
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        dates.append(int(today.timestamp()))
    return dates

def is_slot_in_time_interval(slot_timestamp: int) -> bool:
    """
    Check if the slot (given by its Unix timestamp) falls within the configured time interval.
    Assumes the timestamp is in UTC; adjust if needed.
    """
    slot_time = datetime.utcfromtimestamp(slot_timestamp).time()
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
        return None

    if data.get("success") != 1:
        print(f"No available slots on {datetime.utcfromtimestamp(date_unix).date()}")
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
    overall_message = ""
    
    for date_unix in dates_to_check:
        date_str = datetime.utcfromtimestamp(date_unix).strftime("%Y-%m-%d")
        slots = check_slots_for_date(date_unix)
        if slots:
            overall_message += f"Slots available on {date_str}:\n"
            for slot in slots:
                slot_time_str = datetime.utcfromtimestamp(slot["time"]).strftime("%H:%M")
                overall_message += f" - {slot_time_str} (staff: {slot.get('staff_id')})\n"
        else:
            print(f"No matching slots for {date_str} in the desired time interval.")

    if overall_message:
        print("Sending notification...")
        send_telegram_notification(overall_message)
    else:
        print("No slots available in the specified interval for any checked day.")

if __name__ == "__main__":
    main()
