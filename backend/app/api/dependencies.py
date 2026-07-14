from typing import Annotated

from fastapi import Header


async def participant_token(
    authorization: Annotated[str | None, Header()] = None,
) -> str | None:
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token

