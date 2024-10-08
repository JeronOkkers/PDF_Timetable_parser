import os
import base64
import requests
import time
from flask import Flask, jsonify, request, send_file
from ics import Calendar, Event
from datetime import datetime

app = Flask(__name__)

# Set the folder to upload PDF files and store ICS files
UPLOAD_FOLDER = 'C:/Users/okker/OneDrive/Desktop/Timetable/'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# DocuPanda API details (replace with actual details)
DOCUPANDA_API_URL = "https://app.docupanda.io/document"
DOCUPANDA_API_KEY = "RiKG6uVg85SK46Ozzz8kbFEwI802"  # Replace with your actual API key
DOCUPANDA_STANDARDIZE_URL = "https://app.docupanda.io/standardize/batch"  # URL for standardization
SCHEMA_ID = "0c3784a4"  # Replace with your actual schema ID

@app.route('/upload_pdf', methods=['POST'])
def upload_pdf():
    # Check if the request contains a file
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']

    # Check if a file was uploaded
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if file:
        # Validate file type
        if not allowed_file(file.filename):
            return jsonify({"error": "Unsupported file type. Please upload a PDF."}), 400

        # Save the uploaded file
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)

        try:
            # Step 1: Post PDF to DocuPanda API and get the document ID
            document_id = post_pdf_to_docupanda(file_path)

            # Step 2: Poll the DocuPanda API until processing is complete
            docupanda_response = poll_for_processed_document(document_id)

            # Step 3: Standardize the document
            standardization_id = standardize_document(document_id)

            # Step 4: Poll for the standardization result
            standardized_response = poll_for_standardization_result(standardization_id)

            # Step 5: Process the standardized response and create ICS
            ics_file_path = create_ics_from_standardized_json(standardized_response)

            # Optionally, remove the uploaded PDF after processing
            os.remove(file_path)

            # Return the ICS file as a downloadable response
            return send_file(ics_file_path, as_attachment=True)

        except Exception as e:
            return jsonify({"error": f"Failed to process PDF: {str(e)}"}), 500

def allowed_file(filename):
    """
    Validate the uploaded file's extension.
    """
    return '.' in filename and filename.lower().endswith('.pdf')

def post_pdf_to_docupanda(file_path):
    """
    Post the PDF to DocuPanda and retrieve the document ID.
    """
    # Encode the file in base64
    with open(file_path, 'rb') as file:
        file_contents = base64.b64encode(file.read()).decode()

    # Prepare the payload with the encoded file
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

    # Send the request to DocuPanda
    response = requests.post(DOCUPANDA_API_URL, json=payload, headers=headers)

    # Check if the response is OK
    if response.status_code != 200:
        raise Exception(f"Failed to upload PDF to DocuPanda: {response.text}")
    
    # Get the document ID from the response
    document_id = response.json().get('documentId')
    if not document_id:
        raise Exception("Failed to get document ID from DocuPanda.")
    
    return document_id

def poll_for_processed_document(document_id, max_attempts=10, wait_time=5):
    """
    Polls DocuPanda to check if the document has finished processing.
    """
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

        # Log the full JSON response for debugging
        app.logger.debug(f"DocuPanda Response (Attempt {attempt}): {result}")

        # Check if the document is done processing
        if result.get("status") == "completed":
            return result

        # If not done, wait before the next attempt
        app.logger.info(f"Document status: {result.get('status')}. Retrying in {wait_time} seconds...")
        time.sleep(wait_time)

    raise TimeoutError("Document processing timed out. Please try again later.")

def standardize_document(document_id):
    """
    Send a request to standardize the document.
    """
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

    # Log the response for debugging
    app.logger.debug(f"Standardization Request Response: {response.json()}")

    if response.status_code != 200:
        raise Exception(f"Failed to standardize document: {response.text}")

    # Extract the standardization ID from the response
    standardization_ids = response.json().get('standardizationIds', [])
    if not standardization_ids:
        raise Exception("Standardization request did not return a valid ID.")

    # Assuming we want the first standardization ID
    standardization_id = standardization_ids[0]

    return standardization_id

def poll_for_standardization_result(standardization_id, max_attempts=10, wait_time=5):
    """
    Polls DocuPanda to check if the standardization has completed.
    """
    url = f"https://app.docupanda.io/standardize/{standardization_id}"
    headers = {
        "accept": "application/json",
        "X-API-Key": DOCUPANDA_API_KEY
    }

    for attempt in range(1, max_attempts + 1):
        app.logger.debug(f"Polling for standardization result at {url} (Attempt {attempt}/{max_attempts})")
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            raise Exception(f"Failed to retrieve standardization results: {response.text}")

        result = response.json()

        # Log the full JSON response for debugging
        app.logger.debug(f"Standardization Response (Attempt {attempt}): {result}")

        # Check if the standardization is done
        if result.get("status") == "completed":
            return result
        
        # If not done, wait before the next attempt
        app.logger.info(f"Standardization status: {result.get('status')}. Retrying in {wait_time} seconds...")
        time.sleep(wait_time)

    raise TimeoutError("Standardization processing timed out. Please try again later.")

def create_ics_from_standardized_json(standardized_response):
    """
    Convert the standardized JSON into an ICS (iCalendar) file.
    """
    data = standardized_response.get("result", {})
    
    # Initialize a new calendar
    cal = Calendar()

    # Example: Based on the provided API documentation, the standardized JSON might look like:
    # {
    #     "monthlyAmount": 2000,
    #     "currency": "USD",
    #     "moveInDate": "2020-01-31", 
    #     "depositAmount": 3000, 
    #     "depositCurrency": "USD"
    # }
    #
    # We'll create an event for the move-in date.

    move_in_date_str = data.get("moveInDate")
    if not move_in_date_str:
        raise Exception("Move-in date is missing in the standardized JSON.")

    try:
        move_in_date = datetime.strptime(move_in_date_str, "%Y-%m-%d")
    except ValueError as ve:
        raise Exception(f"Invalid move-in date format: {ve}")

    event = Event()
    event.name = "Move-In Date"
    event.begin = move_in_date
    event.duration = {"days": 1}  # Assuming it's a one-day event
    event.description = f"Move in with deposit of {data.get('depositAmount')} {data.get('depositCurrency')}."
    # Optionally, add more details as needed
    event.location = "Rental Property Address"  # Replace with actual location if available

    cal.events.add(event)

    # Define the path for the ICS file
    ics_filename = f"calendar_{int(time.time())}.ics"
    ics_file_path = os.path.join(app.config['UPLOAD_FOLDER'], ics_filename)

    # Write the calendar to the ICS file
    with open(ics_file_path, 'w') as ics_file:
        ics_file.writelines(cal)

    return ics_file_path

if __name__ == '__main__':
    # Set logging level to DEBUG for detailed logs
    import logging
    logging.basicConfig(level=logging.DEBUG)
    app.run(debug=True)
