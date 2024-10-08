import os
import re
import base64
import requests
import time
import json
from flask import Flask, jsonify, request, send_file
from ics import Calendar, Event
from datetime import datetime, timedelta

app = Flask(__name__)

# Set the folder to upload PDF files and store ICS files
UPLOAD_FOLDER = 'C:/Users/okker/OneDrive/Desktop/Timetable/'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# DocuPanda API details (replace with actual details)
DOCUPANDA_API_URL = "https://app.docupanda.io/document"
DOCUPANDA_API_KEY = "fIUOJroukUQtjvolw2lPf2JArPf2"  # Replace with your actual API key
DOCUPANDA_STANDARDIZE_URL = "https://app.docupanda.io/standardize/batch"  # URL for standardization
DOCUPANDA_STANDARDIZATION_URL = "https://app.docupanda.io/standardization"  # Correct endpoint for standardization results
SCHEMA_ID = "10288f11"  # Replace with your actual schema ID

# Define the actual start date for your academic year
ACTUAL_START_DATE = datetime(2024, 7, 22)  # Start of the term, based on the timetable
  # Replace with the actual start date

# Mapping of week numbers to actual start dates from the timetable
WEEK_START_DATES = {
    'w30': datetime(2024, 7, 22),
    'w31': datetime(2024, 7, 29),
    'w32': datetime(2024, 8, 5),
    'w33': datetime(2024, 8, 12),
    'w34': datetime(2024, 8, 19),
    'w35': datetime(2024, 8, 26),
    'w36': datetime(2024, 9, 2),
    'w37': datetime(2024, 9, 9),
    'w38': datetime(2024, 9, 16),
    'w39': datetime(2024, 9, 23),
    'w40': datetime(2024, 9, 30),
    'w41': datetime(2024, 10, 7),
    'w42': datetime(2024, 10, 14),
    'w43': datetime(2024, 10, 21),
    'w44': datetime(2024, 10, 28),
    'w45': datetime(2024, 11, 4),
    'w46': datetime(2024, 11, 11),
    'w47': datetime(2024, 11, 18),
    'w48': datetime(2024, 11, 25),
    'w49': datetime(2024, 12, 2),
    'w50': datetime(2024, 12, 9),
    'w51': datetime(2024, 12, 16)
}


@app.route('/upload_pdf', methods=['POST'])
def upload_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if file:
        if not allowed_file(file.filename):
            return jsonify({"error": "Unsupported file type. Please upload a PDF."}), 400

        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)
        app.logger.info(f"File saved to {file_path}")

        try:
            # Step 1: Post PDF to DocuPanda API and get the document ID
            document_id = post_pdf_to_docupanda(file_path)
            app.logger.info(f"Document ID received: {document_id}")

            # Step 2: Poll the DocuPanda API until processing is complete
            docupanda_response = poll_for_processed_document(document_id)
            app.logger.info("PDF successfully processed by DocuPanda.")

            # Step 3: Standardize the document
            standardization_id = standardize_document(document_id)
            app.logger.info(f"Standardization ID received: {standardization_id}")

            # Step 4: Poll for the standardization result
            standardized_response = poll_for_standardization_result(standardization_id)
            app.logger.debug(f"Standardized response: {json.dumps(standardized_response, indent=2)}")

            # Save standardized response to JSON file
            json_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'standardized_response.json')
            with open(json_file_path, 'w') as json_file:
                json.dump(standardized_response, json_file, indent=2)

            # Step 5: Process the standardized response and create ICS
            ics_file_path = create_ics_from_standardized_json(standardized_response)

            if not ics_file_path:
                return jsonify({"error": "Failed to create ICS file due to empty timetable data."}), 500

            # os.remove(file_path)
            # app.logger.info(f"Deleted uploaded PDF file: {file_path}")

            return send_file(ics_file_path, as_attachment=True)

        except Exception as e:
            app.logger.error(f"Failed to process PDF: {str(e)}")
            return jsonify({"error": f"Failed to process PDF: {str(e)}"}), 500

def allowed_file(filename):
    return '.' in filename and filename.lower().endswith('.pdf')

def post_pdf_to_docupanda(file_path):
    with open(file_path, 'rb') as file:
        file_contents = base64.b64encode(file.read()).decode()

    payload = {
        "document": {
            "file": {
                "contents": file_contents,
                "filename": os.path.basename(file_path)
            }
        }
    }

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-API-Key": DOCUPANDA_API_KEY
    }

    response = requests.post(DOCUPANDA_API_URL, json=payload, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Failed to upload PDF to DocuPanda: {response.text}")
    
    document_id = response.json().get('documentId')
    if not document_id:
        raise Exception("Failed to get document ID from DocuPanda.")
    
    return document_id

def poll_for_processed_document(document_id, max_attempts=20, wait_time=5):
    url = f"https://app.docupanda.io/document/{document_id}"
    headers = {
        "accept": "application/json",
        "X-API-Key": DOCUPANDA_API_KEY
    }

    for attempt in range(1, max_attempts + 1):
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            raise Exception(f"Failed to retrieve document results: {response.text}")

        result = response.json()
        app.logger.debug(f"DocuPanda Response (Attempt {attempt}): {result}")

        if result.get("status") == "completed":
            return result

        app.logger.info(f"Document status: {result.get('status')}. Retrying in {wait_time} seconds...")
        time.sleep(wait_time)

    raise TimeoutError("Document processing timed out. Please try again later.")

def standardize_document(document_id):
    payload = {
        "documentIds": [document_id],
        "schemaId": SCHEMA_ID
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-API-Key": DOCUPANDA_API_KEY
    }

    response = requests.post(DOCUPANDA_STANDARDIZE_URL, json=payload, headers=headers)
    app.logger.debug(f"Standardization Request Response: {response.json()}")

    if response.status_code != 200:
        raise Exception(f"Failed to standardize document: {response.text}")

    standardization_ids = response.json().get('standardizationIds', [])
    if not standardization_ids:
        raise Exception("Standardization request did not return a valid ID.")

    return standardization_ids[0]

def poll_for_standardization_result(standardization_id, max_attempts=30, wait_time=5):
    url = f"{DOCUPANDA_STANDARDIZATION_URL}/{standardization_id}"
    headers = {
        "accept": "application/json",
        "X-API-Key": DOCUPANDA_API_KEY
    }

    for attempt in range(1, max_attempts + 1):
        app.logger.debug(f"Polling for standardization result at {url} (Attempt {attempt}/{max_attempts})")
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            app.logger.info("Standardization completed successfully.")
            return response.json()
        elif response.status_code == 404:
            app.logger.warning("Standardization not found, will retry...")
            time.sleep(wait_time)
            continue
        else:
            app.logger.error(f"Error fetching status: {response.status_code} - {response.text}")

        time.sleep(wait_time)

    raise TimeoutError("Standardization processing timed out. Please try again later.")


def create_ics_from_standardized_json(standardized_response):
    app.logger.debug(f"Full standardized response: {json.dumps(standardized_response, indent=2)}")
    data = standardized_response.get("data", {})
    timetable = data.get('timetable', None)

    if not timetable:
        app.logger.warning("No timetable data found in the standardized response.")
        return None

    # Create a new calendar
    cal = Calendar()

    for week in timetable:
        week_info = week.get('days', {})
        for day, sessions in week_info.items():  # Loop over each day and its sessions
            for session in sessions:
                event = Event()
                event.name = session.get('module', 'No Module Name')

                # Get the correct date for the event
                event_date = get_date_from_week_and_day(week.get('week'), day)

                if not event_date:
                    app.logger.error(f"Failed to get a valid date for week: {week.get('week')} and day: {day}")
                    continue

                # Parse the start and end times
                start_time_str, end_time_str = session.get('time', '').split(' - ')
                
                try:
                    # Convert time from "10H00" format to hours and minutes
                    start_hour, start_minute = map(int, start_time_str[:-1].split('H'))
                    end_hour, end_minute = map(int, end_time_str[:-1].split('H'))
                except ValueError as e:
                    app.logger.error(f"Error parsing time '{start_time_str}': {e}")
                    continue

                # Combine date and time for event start and end
                start_datetime = datetime(event_date.year, event_date.month, event_date.day, start_hour, start_minute)
                end_datetime = datetime(event_date.year, event_date.month, event_date.day, end_hour, end_minute)

                event.begin = start_datetime.strftime('%Y%m%dT%H%M%SZ')
                event.end = end_datetime.strftime('%Y%m%dT%H%M%SZ')

                # Add the event to the calendar
                cal.events.add(event)

    # Save the calendar as an ICS file
    ics_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'timetable.ics')
    with open(ics_file_path, 'w', encoding='utf-8') as ics_file:
        ics_file.writelines(cal.serialize_iter())

    app.logger.info(f"ICS file created at {ics_file_path}")
    return ics_file_path


#Adjust the function to use the above mapping for actual start dates
def get_date_from_week_and_day(week, day):
    """Calculates the date based on the week number and day name."""
    try:
        # Extract the numeric part of the week string (e.g., "w38 AW8 FP5" -> "w38")
        match = re.match(r'(w\d+)', week)
        if not match:
            raise ValueError(f"Invalid week format: {week}")

        # Extract the week key (e.g., "w38")
        week_key = match.group(1)
        
        # Get the start date of the specified week
        start_date = WEEK_START_DATES.get(week_key)
        if not start_date:
            raise ValueError(f"Invalid week: {week_key}")

        # Define days of the week mapping
        days_ahead = {
            'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3,
            'Fri': 4, 'Sat': 5, 'Sun': 6
        }.get(day, 0)  # Default to Monday if not found

        # Calculate the final date by adding the day offset to the start of the week
        return start_date + timedelta(days=days_ahead)
    
    except Exception as e:
        app.logger.error(f"Failed to calculate date for week {week} and day {day}: {e}")
        return None         


if __name__ == '__main__':
    app.run(debug=True)
