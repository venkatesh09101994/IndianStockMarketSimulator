from typing import Optional
from pydantic import BaseModel

class ReplayConfig(BaseModel):
    enabled: bool
    speed_seconds: int = 2

class AccountResetRequest(BaseModel):
    # Amount in rupees. Omitted means the default of 1 lakh.
    amount: Optional[float] = None

class AccountResetResponse(BaseModel):
    message: str
    new_balance: float
    starting_balance: Optional[float] = None
