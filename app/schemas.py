from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.casefold()
        if len(normalized) > 254:
            raise ValueError("Email is too long")
        return normalized


    @field_validator("password")
    @classmethod
    def validate_encoding(cls, password: SecretStr) -> SecretStr:
        try:
            password.get_secret_value().encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Password must contain valid Unicode") from None
        return password


class Registration(Credentials):
    @field_validator("password")
    @classmethod
    def validate_password(cls, password: SecretStr) -> SecretStr:
        value = password.get_secret_value()
        if len(value) < 15 or not value.strip():
            raise ValueError("Use a password of at least 15 characters")
        return password


class Profile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    created_at: datetime


class Health(BaseModel):
    status: str
