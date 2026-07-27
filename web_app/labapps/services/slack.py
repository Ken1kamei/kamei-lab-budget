import hashlib
import logging
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.cache import cache


logger = logging.getLogger(__name__)
SLACK_USER_SCOPES = [
    "channels:read",
    "groups:read",
    "im:read",
    "mpim:read",
    "channels:history",
    "groups:history",
    "im:history",
    "mpim:history",
    "users:read",
    "users:read.email",
]


class SlackIntegrationError(Exception):
    pass


def slack_configured():
    return all(
        [
            settings.SLACK_CLIENT_ID,
            settings.SLACK_CLIENT_SECRET,
            settings.SLACK_REDIRECT_URI,
            settings.SLACK_TEAM_ID,
            settings.SLACK_TOKEN_ENCRYPTION_KEY,
        ]
    )


def _fernet():
    try:
        return Fernet(settings.SLACK_TOKEN_ENCRYPTION_KEY.encode("ascii"))
    except (ValueError, TypeError) as error:
        raise SlackIntegrationError("Slack token encryption is not configured correctly.") from error


def encrypt_token(token):
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_token(ciphertext):
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as error:
        raise SlackIntegrationError("The saved Slack connection can no longer be decrypted.") from error


def oauth_authorize_url(state):
    if not slack_configured():
        raise SlackIntegrationError("Slack integration is not configured.")
    return "https://slack.com/oauth/v2/authorize?" + urlencode(
        {
            "client_id": settings.SLACK_CLIENT_ID,
            "redirect_uri": settings.SLACK_REDIRECT_URI,
            "state": state,
            "team": settings.SLACK_TEAM_ID,
            "user_scope": ",".join(SLACK_USER_SCOPES),
        }
    )


def _api(method, token, params=None):
    try:
        response = requests.get(
            f"https://slack.com/api/{method}",
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        logger.warning("Slack API %s unavailable: %s", method, error)
        raise SlackIntegrationError("Slack is temporarily unavailable. Please try again.") from error
    if not payload.get("ok"):
        raise SlackIntegrationError(str(payload.get("error") or "Slack API request failed."))
    return payload


def exchange_code(code):
    try:
        response = requests.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": settings.SLACK_CLIENT_ID,
                "client_secret": settings.SLACK_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.SLACK_REDIRECT_URI,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        logger.warning("Slack OAuth unavailable: %s", error)
        raise SlackIntegrationError("Slack authorization is temporarily unavailable.") from error
    if not payload.get("ok"):
        raise SlackIntegrationError(str(payload.get("error") or "Slack authorization failed."))

    authed_user = payload.get("authed_user") or {}
    token = str(authed_user.get("access_token") or "")
    if not token:
        raise SlackIntegrationError("Slack did not return a user access token.")
    identity = _api("auth.test", token)
    if identity.get("team_id") != settings.SLACK_TEAM_ID:
        raise SlackIntegrationError(
            f"Please choose the {settings.SLACK_TEAM_NAME} workspace."
        )
    profile_payload = _api("users.info", token, {"user": identity.get("user_id")})
    profile = (profile_payload.get("user") or {}).get("profile") or {}
    scopes = str(authed_user.get("scope") or "").split(",")
    return {
        "token": token,
        "team_id": str(identity.get("team_id") or ""),
        "team_name": str(identity.get("team") or settings.SLACK_TEAM_NAME),
        "user_id": str(identity.get("user_id") or ""),
        "user_name": str(profile.get("display_name") or profile.get("real_name") or identity.get("user") or "Slack user"),
        "email": str(profile.get("email") or ""),
        "scopes": [scope for scope in scopes if scope],
    }


def _conversation_label(conversation, current_user_id):
    if conversation.get("is_im"):
        return "Direct message"
    if conversation.get("is_mpim"):
        return str(conversation.get("name") or "Group message")
    return f"#{conversation.get('name') or conversation.get('id')}"


def _message_context(message, zone):
    try:
        timestamp = datetime.fromtimestamp(float(message.get("ts") or 0), tz=zone)
    except (TypeError, ValueError, OSError):
        timestamp = None
    return {
        "user_id": str(message.get("user") or ""),
        "text": str(message.get("text") or ""),
        "time_label": timestamp.strftime("%a %H:%M") if timestamp else "",
    }


def _slack_user_label(token, user_id, current_user_id):
    if not user_id:
        return "Slack"
    if user_id == current_user_id:
        return "You"
    cache_key = f"slack-user:{user_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    try:
        payload = _api("users.info", token, {"user": user_id})
        user = payload.get("user") or {}
        profile = user.get("profile") or {}
        label = str(
            profile.get("display_name")
            or profile.get("real_name")
            or user.get("real_name")
            or user.get("name")
            or "Lab member"
        )
    except SlackIntegrationError:
        label = "Lab member"
    cache.set(cache_key, label, 3600)
    return label


def slack_workspace_context(connection, selected_channel=""):
    token = decrypt_token(connection.access_token_ciphertext)
    cache_identity = hashlib.sha256(connection.portal_email.encode("utf-8")).hexdigest()[:16]
    cache_key = f"slack-conversations:{cache_identity}"
    conversations = cache.get(cache_key)
    if conversations is None:
        payload = _api(
            "users.conversations",
            token,
            {
                "types": "public_channel,private_channel,mpim,im",
                "exclude_archived": "true",
                "limit": 100,
            },
        )
        conversations = [
            {
                "id": str(item.get("id") or ""),
                "name": _conversation_label(item, connection.slack_user_id),
                "is_private": bool(item.get("is_private") or item.get("is_im") or item.get("is_mpim")),
            }
            for item in payload.get("channels", [])
            if item.get("id")
        ]
        cache.set(cache_key, conversations, 300)

    allowed_ids = {item["id"] for item in conversations}
    channel_id = selected_channel if selected_channel in allowed_ids else ""
    if not channel_id and conversations:
        channel_id = conversations[0]["id"]
    selected = next((item for item in conversations if item["id"] == channel_id), None)
    messages = []
    if selected:
        history_key = f"slack-history:{cache_identity}:{channel_id}"
        messages = cache.get(history_key)
        if messages is None:
            payload = _api("conversations.history", token, {"channel": channel_id, "limit": 15})
            zone = ZoneInfo(settings.LAB_CALENDAR_TIME_ZONE)
            messages = [_message_context(item, zone) for item in payload.get("messages", [])]
            for message in messages:
                message["user_label"] = _slack_user_label(
                    token, message["user_id"], connection.slack_user_id
                )
                if not message["text"]:
                    message["text"] = "Attachment or app message"
            cache.set(history_key, messages, 60)

    return {
        "status": "ready",
        "connection": connection,
        "conversations": conversations,
        "selected": selected,
        "messages": messages,
        "workspace_url": (
            f"https://app.slack.com/client/{connection.slack_team_id}/{channel_id}"
            if channel_id
            else f"https://app.slack.com/client/{connection.slack_team_id}"
        ),
    }
