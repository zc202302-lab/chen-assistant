"""Application-owned compatibility adapter; never patches the Starlette class."""
from starlette.templating import Jinja2Templates as StarletteJinja2Templates


class Jinja2Templates(StarletteJinja2Templates):
    def TemplateResponse(self, *args, **kwargs):
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
            return super().TemplateResponse(request, name, context, *args[2:], **kwargs)
        if not args and 'name' in kwargs and 'request' not in kwargs:
            context = kwargs.get('context') or {}
            if isinstance(context, dict) and context.get('request') is not None:
                kwargs['request'] = context['request']
        return super().TemplateResponse(*args, **kwargs)
