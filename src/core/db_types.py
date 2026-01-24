from typing import Annotated
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import mapped_column

# Alias - Primary Key
intpk = Annotated[int, mapped_column(primary_key=True)]

# Alias - aware date.
aware_datetime = Annotated[
    datetime,
    mapped_column(DateTime(timezone=True), nullable=False)
]
