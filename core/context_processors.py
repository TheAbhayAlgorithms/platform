from django.conf import settings

def platform_context(request):
    """
    Exposes platform-level constants to all templates.
    """
    return {
        'INSTITUTE_NAME': getattr(settings, 'INSTITUTE_NAME', 'RailClub Connect'),
        'WHATSAPP_SENDER_NUMBER': getattr(settings, 'WHATSAPP_SENDER_NUMBER', '7039145304'),
    }
