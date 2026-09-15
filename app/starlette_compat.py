from __future__ import annotations

from functools import wraps
from typing import Any

from starlette.templating import Jinja2Templates


_INSTALLED = False


def install_template_response_compat() -> None:
    """Keep the project's historical ``TemplateResponse(name, context, ...)`` calls working.

    Starlette 1.0 removed the long-deprecated positional signature and now requires
    ``TemplateResponse(request, name, context, ...)``. The application has many
    mature route modules that still use the former API. Security fixes require a
    current Starlette, while rewriting every historical view during a bug-audit
    would create unnecessary regression risk. This narrow adapter translates only
    the old call shape and leaves the current Starlette API untouched.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    original = Jinja2Templates.TemplateResponse

    @wraps(original)
    def compatible(self: Jinja2Templates, *args: Any, **kwargs: Any):
        # Historical positional form:
        #   TemplateResponse(name, context, status_code=..., ...)
        if args and isinstance(args[0], str):
            name = args[0]
            context = args[1] if len(args) > 1 else kwargs.pop('context', None)
            if context is None:
                context = {}
            if not isinstance(context, dict):
                raise TypeError('template context must be a dict')
            request = kwargs.pop('request', None) or context.get('request')
            if request is None:
                raise ValueError('TemplateResponse context must include request')
            return original(self, request, name, context, *args[2:], **kwargs)

        # Historical keyword form:
        #   TemplateResponse(name='x.html', context={'request': request, ...})
        if not args and 'name' in kwargs and 'request' not in kwargs:
            context = kwargs.get('context') or {}
            if isinstance(context, dict) and context.get('request') is not None:
                kwargs['request'] = context['request']

        return original(self, *args, **kwargs)

    Jinja2Templates.TemplateResponse = compatible
    _INSTALLED = True
