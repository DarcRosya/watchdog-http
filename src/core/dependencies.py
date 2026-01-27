from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from src.core.database import DBSession
from src.models.user import User
from src.services.user import UserService


# Define where to extract the API key from (Header)
api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="API key for authentication. Get it from POST /users/ or POST /auth/"
)


async def get_current_user(
    session: DBSession,
    api_key: str | None = Depends(api_key_header)
) -> User:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is missing. Provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"}
        )
    
    service = UserService(session)
    user = await service.get_user_by_api_key(api_key)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "ApiKey"}
        )
    
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
