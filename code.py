import os
import datetime
import streamlit as st
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Directory to store user credentials
SERVICE_ACCOUNTS_DIR = 'service_accounts'
SCOPES = ["https://www.googleapis.com/auth/calendar"]

def authenticate():
    """Handle user authentication and return credentials."""
    creds = None
    token_path = os.path.join(SERVICE_ACCOUNTS_DIR, 'token.json')

    # Check if token file exists
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # If no valid credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = Flow.from_client_secrets_file('credentials.json', SCOPES)
            flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'  # Using 'out-of-band' for user input
            auth_url, _ = flow.authorization_url(prompt='consent')
            st.write('Please go to this URL and authorize access:')
            st.write(auth_url)

            code = st.text_input('Enter the authorization code here:')
            if code:
                flow.fetch_token(code=code)
                creds = flow.credentials
                # Save the credentials for the next run
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())

    return creds

def fetch_calendar_events(credentials, selected_date):
    """Fetch the events for the selected date from the user's calendar."""
    try:
        service = build('calendar', 'v3', credentials=credentials)
        start_of_day = datetime.datetime.combine(selected_date, datetime.time.min)
        end_of_day = datetime.datetime.combine(selected_date, datetime.time.max)

        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_of_day.astimezone().isoformat(),  # Convert to string
            timeMax=end_of_day.astimezone().isoformat(),    # Convert to string
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        return events
    except HttpError as error:
        st.error(f"An error occurred: {error}")
        return []

def calculate_free_slots(credentials, selected_date):
    """Calculate free slots based on events."""
    # Fetch events for the selected date
    events = fetch_calendar_events(credentials, selected_date)

    # Define working hours
    working_hours_start = datetime.datetime.combine(selected_date, datetime.time(9, 0))
    working_hours_end = datetime.datetime.combine(selected_date, datetime.time(17, 0))

    # Initialize list to store occupied slots
    occupied_slots = []

    # Convert event times to datetime objects and populate occupied slots list
    for event in events:
        start_time = event.get('start', {}).get('dateTime')
        end_time = event.get('end', {}).get('dateTime')
        if start_time and end_time:
            event_start = datetime.datetime.strptime(start_time[:-6], '%Y-%m-%dT%H:%M:%S')
            event_end = datetime.datetime.strptime(end_time[:-6], '%Y-%m-%dT%H:%M:%S')
            occupied_slots.append((event_start, event_end))

    # Sort occupied slots by start time
    occupied_slots.sort()

    # Generate 1-hour time slots throughout the day
    all_slots = []
    current_time = working_hours_start
    while current_time < working_hours_end:
        next_time = current_time + datetime.timedelta(hours=1)
        all_slots.append((current_time, next_time))
        current_time = next_time

    # Remove occupied slots from available slots
    free_slots = []
    prev_event_end = working_hours_start
    for event_start, event_end in occupied_slots:
        if event_start > prev_event_end:
            free_slots.append((prev_event_end, event_start))
        prev_event_end = event_end

    # Add final free slot if there's free time after the last event
    if prev_event_end < working_hours_end:
        free_slots.append((prev_event_end, working_hours_end))

    # Filter free slots to ensure each slot is exactly 1 hour
    filtered_free_slots = []
    for start_time, end_time in free_slots:
        if end_time - start_time == datetime.timedelta(hours=1):
            filtered_free_slots.append((start_time, end_time))
        elif end_time - start_time > datetime.timedelta(hours=1):
            # Split longer slots into 1-hour slots
            current_slot_start = start_time
            while current_slot_start + datetime.timedelta(hours=1) <= end_time:
                current_slot_end = current_slot_start + datetime.timedelta(hours=1)
                filtered_free_slots.append((current_slot_start, current_slot_end))
                current_slot_start = current_slot_end

    return filtered_free_slots

def display_free_slots(free_slots):
    """Display free slots for user selection."""
    st.write("Available time slots:")
    selected_slot = None
    for i, (start, end) in enumerate(free_slots):
        slot_str = f"{start.strftime('%Y-%m-%d %H:%M')} - {end.strftime('%Y-%m-%d %H:%M')}"
        if st.button(slot_str, key=f'slot_{i}'):
            selected_slot = (start, end)
    return selected_slot

def add_event_to_calendar(credentials, start_time, end_time, event_summary):
    """Add an event to the user's calendar."""
    try:
        service = build('calendar', 'v3', credentials=credentials)

        event = {
            'summary': event_summary,
            'description': 'A chance to meet up',
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 10},
                ],
            },
        }

        event = service.events().insert(calendarId='primary', body=event).execute()
        return event
    except HttpError as error:
        # Log the error
        st.error(f"An error occurred: {error}")
        return None

def main():
    st.title('Google Calendar Events Viewer & Scheduler')

    # Authenticate and get credentials
    creds = authenticate()

    if creds:
        st.success('Authenticated successfully.')

        # Allow user to select a date
        selected_date = st.date_input('Select a date', value=datetime.date.today())

        # Fetch events if user clicks on 'Fetch Events' button
        if st.button('Fetch Events'):
            events = fetch_calendar_events(creds, selected_date)
            if events:
                st.write('Events for selected date:')
                for event in events:
                    event_start_time = event.get('start', {}).get('dateTime')
                    event_end_time = event.get('end', {}).get('dateTime')
                    if event_start_time and event_end_time:
                        start_time = datetime.datetime.strptime(event_start_time[:-6], '%Y-%m-%dT%H:%M:%S')
                        end_time = datetime.datetime.strptime(event_end_time[:-6], '%Y-%m-%dT%H:%M:%S')
                        st.write(f"- {event.get('summary', 'No summary available')} (Time: {start_time.time()} - {end_time.time()})")
                    else:
                        st.write(f"- {event.get('summary', 'No summary available')}")
        else:
            events = []  # Initialize events as an empty list if not fetched

        # Calculate and display free slots
        free_slots = calculate_free_slots(creds, selected_date)
        event_summary = st.text_input("Enter event summary:")
        e=event_summary
        selected_slot = display_free_slots(free_slots)
        if selected_slot is not None:
            start_time, end_time = selected_slot
            st.write(selected_slot)
            add_event_button = st.button('Add Event')

                # Display "Proceeding to create event..." message immediately
            message_placeholder = st.empty()
            message_placeholder.write("Proceeding to create event...")

                # Create the event
            event = add_event_to_calendar(creds, start_time, end_time, e)
            if event:
                st.success(f"Event created: {event.get('htmlLink')}")
            else:
                st.warning('Failed to create event. Please try again.')

                # Reset the button press state
        

if __name__ == "__main__":
    if not os.path.exists(SERVICE_ACCOUNTS_DIR):
        os.makedirs(SERVICE_ACCOUNTS_DIR)
    main()
