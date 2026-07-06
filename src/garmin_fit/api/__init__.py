"""FitWeaver Plan API — thin HTTP facade over plan_service.py.

No generation logic lives here: routes parse a request, build a
UnifiedLLMClient from ApiSettings, call the existing plan_service functions,
and serialize the result. See app.create_app().
"""

from .app import create_app

__all__ = ["create_app"]
