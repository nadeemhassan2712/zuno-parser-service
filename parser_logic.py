import pdfplumber
import re
import io
import logging
from typing import List, Optional
from decimal import Decimal, InvalidOperation

# Import the Pydantic models
from models import StatementDetails, Transaction

# Get the logger instance
log = logging.getLogger(__name__)


# --- Custom Exceptions ---

class PasswordError(Exception):
    """Raised when the provided password for the PDF is incorrect."""
    pass


class ParsingError(Exception):
    """Raised when the PDF structure is not recognized."""
    pass


# --- Regex Patterns (Updated for Robustness) ---
# These are compiled once for efficiency.

# Rule 1: Find the card name. We'll capture the full line and clean it later.
# This finds a line ending in "Credit Card Statement"
CARD_NAME_RE = re.compile(r"^\s*(.* Credit Card) Statement", re.MULTILINE)

# Rule 3: Find the Name on Card.
# This looks for a line starting with 10+ ALL CAPS characters (the name)
# followed by spaces, then "Credit Card No."
NAME_ON_CARD_RE = re.compile(r"^\s*([A-Z\s]{10,})\s+Credit Card No\.", re.MULTILINE)

# Rule 2: Find the Last 4 Digits.
# This finds "Credit Card No.", matches any characters (non-greedy),
# then "XXXXXX", and then captures the 4 digits.
CARD_NUMBER_RE = re.compile(r"Credit Card No\..*?XXXXXX(\d{4})")

# --- NEW: Regex for Total Credit Limit (Two Patterns) ---

# Pattern A (for "nadeem pdf.pdf" layout):
# Finds the header line, then captures the *first* "C" amount on the next line.
TOTAL_LIMIT_RE_A = re.compile(
    r"TOTAL CREDIT LIMIT\n"  # Line 1: "TOTAL CREDIT LIMIT"
    r"\s*\(Including Cash\).*AVAILABLE CREDIT LIMIT.*\n"  # Line 2: "(Including Cash) AVAILABLE..."
    r"\s*C?([\d,]+\.?\d*)",  # Line 3: Capture the first amount
    re.MULTILINE
)

# Pattern B (for "pds duplicate arbaaz.pdf" layout):
# Finds the header line, skips 1-2 lines, then captures the amount.
TOTAL_LIMIT_RE_B = re.compile(
    r"TOTAL CREDIT LIMIT\n"  # Line 1: "TOTAL CREDIT LIMIT"
    r"(?:.*\n){1,2}"  # Line 2/3: Skip "AVAILABLE CREDIT..." & "(Including Cash)"
    r"\s*([\d,]+\.?\d*)",  # Line 4: Capture the amount
    re.MULTILINE
)

# Matches transaction dates like "08/10/2025" (at the start of a string)
TX_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}")


# --- Helper Functions ---

def _clean_card_name(full_name: str) -> str:
    """
    Removes the common bank-related words from the
    card name as per the user's request.
    """
    words_to_remove = ["HDFC", "Bank", "Credit", "Card", "Statement"]
    # Create a regex pattern to find any of these words, case-insensitive
    # \b ensures we match whole words only (e.g., "Card" but not "Carding")
    pattern = re.compile(r'\b(' + '|'.join(words_to_remove) + r')\b', re.IGNORECASE)
    cleaned_name = pattern.sub('', full_name)
    # Clean up extra whitespace
    return ' '.join(cleaned_name.split())


def _clean_amount(text: str) -> Optional[Decimal]:
    """
    Converts a string amount like '1,234.56', 'C3,00,000', '1,234.56 Cr', or '+86,962.00' into a Decimal.
    - 'Cr' (Credit) or '+' prefix is treated as a negative number (e.g., a payment).
    - No suffix or 'Dr' is treated as positive (e.g., a purchase).
    - Strips "C", "₹", and ",".
    """
    if not text:
        return None

    text = text.strip().replace(",", "")

    # Check for credits (payments)
    # The Tata Neu card uses '+' for payments.
    is_credit = 'cr' in text.lower() or text.startswith('+')

    # Remove all non-numeric/non-dot characters (including '₹' or 'C')
    # This is the key part that handles "C3,00,000"
    cleaned_text = re.sub(r"[^0-9.]", "", text)

    try:
        if not cleaned_text:
            return None
        amount = Decimal(cleaned_text)
        if is_credit:
            return -amount  # Credits/payments are negative
        return amount  # Debits/purchases are positive
    except (InvalidOperation, ValueError):
        log.warning(f"Could not parse amount: {text}")
        return None


def _is_transaction_table(header: List[str]) -> bool:
    """Check if a table header looks like a transaction table."""
    if not header:
        return False

    # Clean the header row by joining all cells
    header_text = " ".join(filter(None, header)).lower()

    # Check for keywords that are almost always in a transaction table
    return "date" in header_text and "transaction" in header_text and "amount" in header_text


def _parse_transaction_row(row: List[str]) -> Optional[Transaction]:
    """
    Tries to parse a list of strings (a table row) into a Transaction object.
    This is now robust and handles inconsistent columns.
    """
    if not row or len(row) < 3:
        # A valid transaction row must have at least date, merchant, and amount
        return None

    # --- 1. Extract Date ---
    # The date is always the first element. It might have a time " | 11:58"
    date_str = row[0].split('|')[0].strip()
    if not TX_DATE_RE.match(date_str):
        log.debug(f"Skipping row, invalid date format: {date_str}")
        return None  # Not a valid transaction row

    # --- 2. Extract Amount ---
    # The amount is *always* the last element.
    amount_str = row[-1]
    amount = _clean_amount(amount_str)
    if amount is None:
        log.debug(f"Skipping row, invalid amount: {amount_str}")
        return None  # Not a valid transaction row

    # --- 3. Extract Merchant ---
    # The merchant is everything in between the first and last columns,
    # *except* for junk columns (like rewards, EMI, or currency).

    merchant_parts = []
    # Iterate over the middle columns: row[1] to row[second-to-last]
    for part in row[1:-1]:
        if not part:  # Skip empty strings
            continue

        part_stripped = part.strip()

        # This filter removes common "junk" columns.
        # e.g., "EMI", "+57", "1,234 pts", "USD 25.00"
        if part_stripped.upper() == "EMI" or \
                part_stripped.upper() == "EM" or \
                re.match(r"^[+-]\d+$", part_stripped) or \
                re.match(r"^\d+\s+pts$", part_stripped, re.IGNORECASE) or \
                re.match(r"^(USD|EUR|GBP)\s+[\d\.]+$", part_stripped, re.IGNORECASE):
            continue

        merchant_parts.append(part_stripped)

    merchant = " ".join(merchant_parts).strip()

    # Skip footer/summary rows
    if not merchant or merchant.lower().startswith("total"):
        return None

    return Transaction(
        date=date_str,
        merchant=merchant,
        amount=float(amount)  # Convert Decimal to float for JSON
    )


# --- Main Parsing Function ---

def parse_statement(file_bytes: io.BytesIO, password: str) -> StatementDetails:
    """
    Main parsing function. Opens the PDF, extracts text and tables,
    and populates a StatementDetails object.
    """
    pdf = None
    try:
        # 1. Open the PDF
        pdf = pdfplumber.open(file_bytes, password=password)
    except pdfplumber.errors.PasswordError:
        log.warning("PDF password error.")
        raise PasswordError("Invalid password")
    except Exception as e:
        log.error(f"Failed to open PDF. It may be corrupted. Error: {e}")
        raise ParsingError(f"Failed to open PDF: {e}")

    if not pdf:
        raise ParsingError("PDF object is null, cannot proceed.")

    # --- Data Extraction ---
    transactions: List[Transaction] = []
    card_name: Optional[str] = None
    card_last_4_digits: Optional[str] = None
    name_on_card: Optional[str] = None

    # We will store the Total Limit in the 'available_limit' field as per your request.
    total_limit: Optional[float] = None

    # We only need the text from the first page for summary data
    page_one_text = ""

    try:
        log.info(f"PDF opened successfully. {len(pdf.pages)} pages found.")

        # --- Page Loop (for tables) ---
        for i, page in enumerate(pdf.pages):
            # 2. Extract text with layout preservation
            # This is crucial for our regex to understand lines and blocks
            page_text = page.extract_text(x_tolerance=2, layout=True)
            if not page_text:
                continue

            if i == 0:
                # Store page one text for summary regex
                page_one_text = page_text

            # 3. Extract tables from the page
            tables = page.extract_tables(table_settings={
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
            })
            log.info(f"Page {i + 1}: Found {len(tables)} tables.")

            for table in tables:
                if not table:
                    continue

                header = table[0]
                if _is_transaction_table(header):
                    log.info(f"Found transaction table on page {i + 1}")
                    # Iterate rows, skipping the header
                    for row in table[1:]:
                        tx = _parse_transaction_row(row)
                        if tx:
                            transactions.append(tx)

        # 4. Post-process the full text *of page one* with regex
        # This is more stable for finding summary details.

        # Find and clean Card Name (Rule 1)
        if (match := CARD_NAME_RE.search(page_one_text)):
            full_card_name = match.group(1).strip()
            card_name = _clean_card_name(full_card_name)
            log.info(f"Found Card Name: {card_name} (from '{full_card_name}')")

        # Find Name on Card (Rule 3)
        if (match := NAME_ON_CARD_RE.search(page_one_text)):
            # Group 1 is the name
            name_on_card = match.group(1).strip()
            log.info(f"Found Name on Card: {name_on_card}")

        # Find Last 4 Digits (Rule 2)
        if (match := CARD_NUMBER_RE.search(page_one_text)):
            # Group 1 is the 4 digits
            card_last_4_digits = match.group(1)
            log.info(f"Found Last 4 Digits: {card_last_4_digits}")

        # Find Total Credit Limit (User Request)
        # --- NEW LOGIC: Try Pattern A, then Pattern B ---
        limit_str = None
        if (match := TOTAL_LIMIT_RE_A.search(page_one_text)):
            limit_str = match.group(1)
            log.info("Matched Total Limit with Pattern A (Nadeem-style PDF)")
        elif (match := TOTAL_LIMIT_RE_B.search(page_one_text)):
            limit_str = match.group(1)
            log.info("Matched Total Limit with Pattern B (Arbaaz-style PDF)")

        if limit_str:
            limit_decimal = _clean_amount(limit_str)  # Use clean_amount to handle "C" and ","
            if limit_decimal is not None:
                total_limit = float(abs(limit_decimal))  # Use abs() just in case
                log.info(f"Found Total Credit Limit: {total_limit}")
        else:
            log.warning("Could not find Total Credit Limit. Both regex patterns failed.")

        if not transactions:
            log.warning("No transactions were found for file.")
            # We can still return a statement with 0 transactions if summary data was found.

        # 5. Compile the final response
        # We are putting the TOTAL limit into the 'available_limit' field
        # as per your request to match "300000".
        return StatementDetails(
            card_name=card_name,
            card_last_4_digits=card_last_4_digits,
            name_on_card=name_on_card,
            available_limit=total_limit,  # Assigning Total Limit here
            transactions=transactions
        )

    except Exception as e:
        log.error(f"Error during PDF parsing logic: {e}", exc_info=True)
        raise ParsingError(f"Error during PDF parsing: {e}")
    finally:
        if pdf:
            pdf.close()
            log.info("PDF file closed.")

