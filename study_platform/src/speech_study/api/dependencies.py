from typing import Annotated
from fastapi import Depends, Request
from ..container import ApplicationServices


def services(request: Request) -> ApplicationServices:
    return request.app.state.services


ServiceContainer = Annotated[ApplicationServices, Depends(services)]
