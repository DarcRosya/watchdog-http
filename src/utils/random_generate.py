import secrets

from coolname import generate_slug

def generate_random_username() -> str:
    return generate_slug(2)

def generate_api_key() -> str:
    """Generate a secure random API key."""
    return secrets.token_urlsafe(32)