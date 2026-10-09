import datetime
import re
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, WithJsonSchema, field_validator

# Money and quantities are exact Decimals in Python but a plain number in the JSON schema
# the model sees: Pydantic's default Decimal schema adds a string with a regex pattern, which
# Gemini's structured output doesn't support. Constraints such as gt/ge on an Amount are still
# enforced by Pydantic; they just aren't sent to the model. Only the validation (input) schema is
# replaced: API responses carry Decimals as strings, and their documented schema must say so.
Amount = Annotated[Decimal, WithJsonSchema({"type": "number"}, mode="validation")]


class LineItem(BaseModel):
    """One purchased item as printed on the receipt."""

    description: str = Field(description="Item name as printed on the receipt")
    quantity: Amount = Field(gt=0, description="Number of units, or the weight for weighed items; 1 if not printed")
    unit_price: Amount | None = Field(description="Price of one unit; negative for discounts; null if unreadable")


class ExtractedReceipt(BaseModel):
    """Fields extracted from one receipt or invoice. Unreadable fields are null, never guessed."""

    vendor: str | None = Field(description="Business name of the seller")
    # datetime.date, not a bare `date`: on Python 3.14 the annotation would resolve to this field
    date: datetime.date | None = Field(description="Purchase or invoice date")
    total_amount: Amount | None = Field(ge=0, description="Final amount paid, including tax and tip")
    currency: str | None = Field(description="ISO 4217 currency code, e.g. USD or EUR")
    line_items: list[LineItem] = Field(description="Purchased items; excludes subtotal, tax, tip and total lines")

    @field_validator("currency")
    @classmethod
    def currency_is_iso_4217(cls, value: str | None) -> str | None:
        # A validator rather than Field(pattern=...): "pattern" isn't supported in Gemini's schema
        if value is not None and not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("must be a 3-letter ISO 4217 code such as USD")
        return value
