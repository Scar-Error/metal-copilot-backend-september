import logging
from datetime import datetime, timedelta

import msal
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from authentication.models import MicrosoftToken

User = get_user_model()
logger = logging.getLogger(__name__)

MS_AUTHORITY = (
    f'https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}'
)
MS_SCOPE = ['User.Read', 'Mail.Read', 'Mail.Send']
MS_REDIRECT_URI = getattr(
    settings,
    'MICROSOFT_REDIRECT_URI',
    'http://localhost:8000/api/auth/microsoft/callback/',
)
FRONTEND_URL = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')


def _msal_app():
    return msal.ConfidentialClientApplication(
        settings.MICROSOFT_CLIENT_ID,
        authority=MS_AUTHORITY,
        client_credential=settings.MICROSOFT_CLIENT_SECRET,
    )


def _redirect(path: str) -> HttpResponseRedirect:
    return HttpResponseRedirect(f'{FRONTEND_URL}{path}')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def microsoft_login(request):
    try:
        app = _msal_app()
        auth_url = app.get_authorization_request_url(
            scopes=MS_SCOPE,
            redirect_uri=MS_REDIRECT_URI,
            state=str(request.user.id),
        )
        return Response({'success': True, 'auth_url': auth_url})
    except Exception as exc:
        logger.exception('Microsoft login error')
        return Response({'success': False, 'error': str(exc)}, status=500)


@csrf_exempt
@require_http_methods(['GET'])
def microsoft_callback(request):
    error = request.GET.get('error')
    if error:
        logger.error('Microsoft OAuth error: %s', error)
        return _redirect(f'/auth/callback?error={error}')

    code = request.GET.get('code')
    if not code:
        return _redirect('/auth/callback?error=no_code')

    state = request.GET.get('state')
    if not state:
        return _redirect('/auth/callback?error=no_state')

    try:
        user = User.objects.get(id=state)
    except (User.DoesNotExist, ValueError):
        return _redirect('/auth/callback?error=invalid_state')

    try:
        app = _msal_app()
        token_result = app.acquire_token_by_authorization_code(
            code,
            scopes=MS_SCOPE,
            redirect_uri=MS_REDIRECT_URI,
        )

        if 'error' in token_result:
            desc = token_result.get('error_description', 'unknown')
            logger.error('Token acquisition error: %s', desc)
            return _redirect('/auth/callback?error=token_failed')

        access_token = token_result.get('access_token')
        user_info = _get_user_info(access_token)
        if not user_info:
            return _redirect('/auth/callback?error=user_info_failed')

        _connect_ms_token(user, user_info, token_result)

        ms_email = _clean_ms_email(user_info)
        from urllib.parse import quote
        return _redirect(f'/auth/callback?status=success&email={quote(ms_email)}')
    except Exception as exc:
        logger.exception('Microsoft callback error')
        return _redirect(f'/auth/callback?error={str(exc)}')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def refresh_microsoft_token(request):
    try:
        token = request.user.microsoft_token
    except MicrosoftToken.DoesNotExist:
        return Response(
            {'success': False, 'error': 'No Microsoft token'},
            status=404,
        )

    try:
        app = _msal_app()
        result = app.acquire_token_by_refresh_token(
            token.refresh_token,
            scopes=MS_SCOPE,
        )

        if 'error' in result:
            logger.error('Token refresh error: %s', result.get('error_description'))
            return Response(
                {'success': False, 'error': 'Token refresh failed'},
                status=400,
            )

        expires_in = result.get('expires_in', 3600)
        token.access_token = result.get('access_token')
        token.refresh_token = result.get('refresh_token', token.refresh_token)
        token.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
        token.save()

        return Response({
            'success': True,
            'access_token': token.access_token,
            'expires_at': token.token_expires_at.isoformat(),
        })
    except Exception as exc:
        logger.exception('Token refresh error')
        return Response({'success': False, 'error': str(exc)}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def microsoft_status(request):
    try:
        token = request.user.microsoft_token
        return Response({
            'connected': True,
            'email': token.microsoft_email,
            'name': token.microsoft_name,
            'expires_at': token.token_expires_at.isoformat(),
            'scopes': token.scopes,
        })
    except MicrosoftToken.DoesNotExist:
        return Response({'connected': False})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def disconnect_microsoft(request):
    try:
        token = request.user.microsoft_token
        token.delete()
    except MicrosoftToken.DoesNotExist:
        pass

    return Response({'success': True})


def _clean_ms_email(user_info: dict) -> str:
    ms_email = user_info.get('mail')
    if ms_email:
        return ms_email

    upn = user_info.get('userPrincipalName', '')
    if '#EXT#' in upn:
        local = upn.split('#EXT#')[0]
        if '_' in local:
            idx = local.rindex('_')
            return local[:idx] + '@' + local[idx + 1:]
        return local
    return upn


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_user_info(access_token: str):
    try:
        resp = requests.get(
            'https://graph.microsoft.com/v1.0/me',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error('Graph API user info error: %s', exc)
        return None


def _connect_ms_token(user, user_info: dict, token_result: dict):
    ms_id = user_info.get('id')
    ms_email = _clean_ms_email(user_info)
    ms_name = user_info.get('displayName', '')

    # Remove any MicrosoftToken with this microsoft_id that belongs
    # to a different user (leftover from the old login-based flow).
    MicrosoftToken.objects.filter(microsoft_id=ms_id).exclude(user=user).delete()

    expires_in = token_result.get('expires_in', 3600)
    MicrosoftToken.objects.update_or_create(
        user=user,
        defaults={
            'access_token': token_result.get('access_token'),
            'refresh_token': token_result.get('refresh_token', ''),
            'token_expires_at': datetime.now() + timedelta(seconds=expires_in),
            'microsoft_id': ms_id,
            'microsoft_email': ms_email,
            'microsoft_name': ms_name,
            'scopes': ','.join(MS_SCOPE),
            'token_type': token_result.get('token_type', 'Bearer'),
        },
    )

    logger.info('Microsoft account linked to user %s: %s', user.username, ms_email)
