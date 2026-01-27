from fastapi import APIRouter, HTTPException, status

from src.core.database import DBSession
from src.core.dependencies import CurrentUser
from src.schemas.user import UserCreate, UserResponse
from src.schemas.auth import AuthRequest, AuthResponse
from src.services.user import UserService


router = APIRouter(prefix="/users", tags=["Users"])


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user",
    description="Registers a new user in the monitoring system. Returns user data including API key."
)
async def create_user(
    user_data: UserCreate,
    session: DBSession 
):
    service = UserService(session)
    
    # Docker logs output
    print(f"📝 Creating user: {user_data.username}")
    
    user = await service.create_user(
        username=user_data.username,
        telegram_chat_id=user_data.telegram_chat_id
    )
    
    return user


@router.post(
    "/auth",
    response_model=AuthResponse,
    summary="Authenticate and get API key",
    description="Get your API key by providing your username. Use this if you lost your key."
)
async def authenticate(
    auth_data: AuthRequest,
    session: DBSession
):
    service = UserService(session)
    user = await service.get_user_by_username(auth_data.username)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with username='{auth_data.username}' not found"
        )
    
    print(f"🔐 User authenticated: {user.username}")
    return user


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    description="Get information about the currently authenticated user."
)
async def get_current_user_info(user: CurrentUser):
    return user


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get user by ID",
    responses={
        404: {"description": "User not found"}
    }
)
async def get_user(
    user_id: int, 
    session: DBSession,
    _user: CurrentUser  # Require authentication
):
    service = UserService(session)
    user = await service.get_user_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id={user_id} not found"
        )
    
    return user


@router.get(
    "/telegram/{telegram_id}",
    response_model=UserResponse,
    summary="Find a user by Telegram ID",
    responses={
        404: {"description": "No user with this Telegram ID was found."}
    }
)
async def get_user_by_telegram(
    telegram_id: int,
    session: DBSession,
    _user: CurrentUser  # Require authentication
):
    service = UserService(session)
    user = await service.get_user_by_telegram_id(telegram_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with telegram_id={telegram_id} not found"
        )
    
    return user
