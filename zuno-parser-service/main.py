import logging
import io
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

# Import local modules (models.py, parser_logic.py)
from models import StatementDetails, ErrorDetail
from parser_logic import parse_statement, PasswordError, ParsingError

# --- Logging Configuration ---
# Configure logging to output a standard format.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Zuno PDF Parser Service",
    description="A microservice to extract transaction data from bank statements.",
    version="1.0.0"
)


# --- Exception Handlers (Production Grade) ---

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom handler for FastAPI's built-in HTTPExceptions."""
    log.warning(f"HTTPException: {exc.status_code} {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    """
    Generic 500 Internal Server Error handler.
    This catches any unhandled exceptions in the application.
    """
    log.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected internal server error occurred."},
    )


# --- API Endpoints ---

@app.get("/health", tags=["Monitoring"])
async def health_check():
    """Simple health check endpoint to confirm the service is running."""
    log.info("Health check endpoint was hit.")
    return {"status": "ok"}


@app.post(
    "/parse-statement/",
    response_model=StatementDetails,
    tags=["Parsing"],
    responses={
        400: {"model": ErrorDetail, "description": "Invalid password or file type"},
        422: {"model": ErrorDetail, "description": "Failed to parse the PDF structure"},
        500: {"model": ErrorDetail, "description": "Internal server error"},
    }
)
async def parse_pdf_statement(
        password: str = Form(..., description="The password for the PDF file."),
        file: UploadFile = File(..., description="The PDF statement file to parse.")
):
    """
    Main endpoint to parse a password-protected PDF bank statement.

    Accepts a multipart/form-data request with 'password' and 'file'.
    Returns a structured JSON object with the extracted statement details.
    """
    log.info(f"Received parsing request for file: {file.filename}")

    # 1. Basic File Validation
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        log.warning(f"Invalid file type: {file.filename}")
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF files are accepted.")

    try:
        # 2. Read file bytes from the upload
        file_bytes = await file.read()

        # 3. Call the core parsing logic
        log.info(f"Attempting to parse PDF with {len(file_bytes)} bytes...")
        details = parse_statement(
            file_bytes=io.BytesIO(file_bytes),
            password=password
        )

        log.info(f"Successfully parsed statement for: {details.name_on_card}")
        return details

    # 4. Handle known, specific errors from the parser
    except PasswordError:
        log.warning(f"Invalid password attempt for file: {file.filename}")
        raise HTTPException(status_code=400, detail="Invalid password provided for the PDF.")

    except (ParsingError, ValidationError) as e:
        log.error(f"Failed to parse PDF structure for file: {file.filename}. Error: {e}")
        raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {e}")

    # 5. Handle any other unexpected errors
    except Exception as e:
        log.error(f"An unexpected error occurred for file {file.filename}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    import uvicorn

    # This is for local debugging. For production, run with a proper Gunicorn/Uvicorn worker.
    uvicorn.run(app, host="0.0.0.0", port=8000)

