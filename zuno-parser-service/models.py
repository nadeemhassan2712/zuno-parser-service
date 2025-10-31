from pydantic import BaseModel, Field
from typing import List, Optional

class ErrorDetail(BaseModel):
    """A structured error response."""
    detail: str

class Transaction(BaseModel):
    """Defines the structure for a single extracted transaction."""
    date: str = Field(..., description="Transaction date (e.g., '08-Oct-2025')")
    merchant: str = Field(..., description="Merchant name or transaction description")
    amount: float = Field(..., description="Transaction amount. Positive for purchases/debits, negative for payments/credits.")

class StatementDetails(BaseModel):
    """The main response model for a successfully parsed statement."""
    card_name: Optional[str] = Field(None, description="The name of the credit card (e.g., 'Business Regalia First')")
    card_last_4_digits: Optional[str] = Field(None, description="The last 4 digits of the card number")
    name_on_card: Optional[str] = Field(None, description="The name of the cardholder as it appears on the statement")
    available_limit: Optional[float] = Field(None, description="The available credit limit after the statement date")
    transactions: List[Transaction] = Field(..., description="A list of all transactions found in the statement")

