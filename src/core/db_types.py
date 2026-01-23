from typing import Annotated
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import mapped_column

# Alias - Primary Key
intpk = Annotated[int, mapped_column(primary_key=True)]

# Aliases - Str
str_50 = Annotated[str, mapped_column(String(50))]
str_100 = Annotated[str, mapped_column(String(100))]
str_150 = Annotated[str, mapped_column(String(150))]

# Alias - aware date.
aware_datetime = Annotated[
    datetime,
    mapped_column(DateTime(timezone=True), nullable=False)
]
