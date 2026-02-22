from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from src.core.database import DBSession
from src.core.dependencies import CurrentUser
from src.core.logging import get_logger
from src.schemas.user import UserResponse, UserUpdate
from src.schemas.auth import AuthRequest, AuthResponse
from src.services.user import UserService
from src.telegram.bot import refresh_user_monitor_cache

logger = get_logger("api")
router = APIRouter(prefix="/users", tags=["Users"])


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user",
    description="Registers a new user with auto-generated username and API key.",
)
async def create_user(session: DBSession):
    service = UserService(session)

    logger.info("user_registration_attempt")

    user = await service.create_user()

    logger.info("user_created", username=user.username, user_id=user.id)

    return user


@router.post(
    "/auth",
    response_model=AuthResponse,
    summary="Authenticate and get API key",
    description="Get your API key by providing your username. Use this if you lost your key.",
)
async def authenticate(auth_data: AuthRequest, session: DBSession):
    service = UserService(session)
    user = await service.get_user_by_username(auth_data.username)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with username='{auth_data.username}' not found",
        )

    logger.info("user_authenticated", username=user.username, user_id=user.id)
    return user


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    description="Get information about the currently authenticated user.",
)
async def get_current_user_info(user: CurrentUser):
    return user


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update current user profile",
    description="Update your profile settings. Set telegram_chat_id to null to unbind Telegram.",
)
async def update_current_user(
    update_data: UserUpdate,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    session: DBSession,
):
    service = UserService(session)
    updated_user = await service.update_user(user.id, update_data)

    update_dict = update_data.model_dump(exclude_unset=True)
    if "telegram_chat_id" in update_dict:
        background_tasks.add_task(
            refresh_user_monitor_cache, updated_user.id, updated_user.telegram_chat_id
        )

    logger.info(
        "user_profile_updated",
        user_id=user.id,
        username=user.username,
        updated_fields=update_data.model_dump(exclude_unset=True),
    )

    return updated_user


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get user by ID",
    responses={404: {"description": "User not found"}},
)
async def get_user(
    user_id: int, session: DBSession, _user: CurrentUser  # Require authentication
):
    service = UserService(session)
    user = await service.get_user_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id={user_id} not found",
        )

    return user


@router.get(
    "/telegram/{telegram_id}",
    response_model=UserResponse,
    summary="Find a user by Telegram ID",
    responses={404: {"description": "No user with this Telegram ID was found."}},
)
async def get_user_by_telegram(
    telegram_id: int, session: DBSession, _user: CurrentUser  # Require authentication
):
    service = UserService(session)
    user = await service.get_user_by_telegram_id(telegram_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with telegram_id={telegram_id} not found",
        )

    return user
