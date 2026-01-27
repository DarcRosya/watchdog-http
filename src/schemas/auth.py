from pydantic import BaseModel, Field, ConfigDict

class AuthRequest(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=100,
        description="Username to authenticate.",
        examples=["glossy-zebra"]
    )

class AuthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int = Field(description="User ID.")
    username: str = Field(description="The username.")
    api_key: str = Field(description="API key for authentication.")