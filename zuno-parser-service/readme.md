Zuno PDF Parser ServiceThis is a Python microservice built with FastAPI to parse password-protected credit card statements from PDF files.FeaturesExtracts statement summary (Card Name, Holder Name, etc.)Extracts all individual transactions from tablesHandles password-protected filesProvides a clean, production-grade JSON APIRunning the Service1. InstallationIt is highly recommended to run this in a Python virtual environment.# Create a virtual environment
python -m venv venv
# Activate it (macOS/Linux)
source venv/bin/activate
# Or (Windows)
.\venv\Scripts\activate

# Install all required dependencies
pip install -r requirements.txt
2. Running for DevelopmentUse uvicorn with auto-reload.uvicorn main:app --reload
The service will be available at http://127.0.0.1:8000.You can access the interactive API documentation at http://127.0.0.1:8000/docs.3. Running for ProductionUse a production-grade WSGI server like Gunicorn to manage Uvicorn workers.# Example: Run 4 worker processes
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app
API EndpointPOST /parse-statement/Parses the provided PDF and returns structured JSON.Request: multipart/form-datapassword (string): The password for the PDF file.file (file): The .pdf file to be parsed.Example cURL Request:curl -X 'POST' \
  '[http://127.0.0.1:8000/parse-statement/](http://127.0.0.1:8000/parse-statement/)' \
  -H 'accept: application/json' \
  -H 'Content-Type: multipart/form-data' \
  -F 'password=ARBA1412' \
  -F 'file=@/path/to/your/statement.pdf'
Success Response (200 OK):{
  "card_name": "Business Regalia First Credit Card",
  "card_last_4_digits": "1234",
  "name_on_card": "ARBAAZ KHAN",
  "available_limit": 150000.0,
  "transactions": [
    {
      "date": "08-Oct-2025",
      "merchant": "AMAZON PAY INDIA",
      "amount": 1500.75
    },
    {
      "date": "10-Oct-2025",
      "merchant": "PAYMENT RECEIVED - THANK YOU",
      "amount": -5000.0
    }
  ]
}
Error Responses:400 Bad Request: If the password is wrong or the file is not a PDF.422 Unprocessable Entity: If the PDF is parsed but the required data (e.g., transaction tables) cannot be found.500 Internal Server Error: If an unexpected error occurs.