"""OTP-based authentication and access request flows."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import secrets
from sqlite3 import Connection
from uuid import uuid4

from gtv.config import Settings
from gtv.constants import OTP_MAX_ATTEMPTS, OTP_RESEND_SECONDS, OTP_VALID_MINUTES
from gtv.models import AuthenticatedUser
from gtv.repositories import notifications as notification_repo
from gtv.repositories import users as user_repo
from gtv.services import auditing
from gtv.services.mailer import send_email


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _to_authenticated_user(row: dict) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=row["id"],
        email=row["email"],
        full_name=row["full_name"],
        preferred_name=row.get("preferred_name") or row["full_name"],
        role=row["role"],
        status=row["status"],
        is_seed=bool(row["is_seed"]),
    )


def request_login_or_access(
    connection: Connection,
    settings: Settings,
    *,
    email: str,
    full_name: str | None = None,
    preferred_name: str | None = None,
) -> dict:
    normalized_email = email.strip().lower()
    requested_name = (full_name or normalized_email.split("@")[0]).strip()
    requested_preferred_name = (preferred_name or requested_name.split()[0]).strip()
    user = user_repo.get_user_by_email(connection, normalized_email)

    if user and user["status"] == "activo":
        active_otp = user_repo.get_active_otp(connection, user["id"])
        if active_otp and active_otp["resend_available_at"] > _now():
            return {
                "status": "otp_wait",
                "message": "Ya existe un OTP vigente. Espera unos segundos para reenviar.",
            }
        return _issue_otp(connection, settings, user)

    if user and user["status"] == "pendiente_aprobacion":
        request = user_repo.get_pending_access_request_for_user(connection, user["id"])
        return {
            "status": "pending",
            "message": "Tu acceso sigue pendiente de aprobacion.",
            "request_id": request["id"] if request else None,
        }

    if user and user["status"] in {"rechazado", "deshabilitado"}:
        return {
            "status": "blocked",
            "message": f"Tu usuario esta en estado {user['status']}. Contacta a un administrador semilla.",
        }

    user_id = user_repo.create_pending_user(
        connection,
        email=normalized_email,
        full_name=requested_name,
    )
    request_id = user_repo.create_access_request(
        connection,
        user_id=user_id,
        email=normalized_email,
        requested_name=requested_name,
        requested_preferred_name=requested_preferred_name,
    )
    _notify_seed_admins_of_access_request(
        connection,
        settings,
        requester_email=normalized_email,
        requester_name=requested_name,
        requester_preferred_name=requested_preferred_name,
        request_id=request_id,
    )
    auditing.audit_event(
        connection,
        user_email=normalized_email,
        entity_type="access_request",
        entity_id=str(request_id),
        action="solicitud_creada",
        context="Solicitud inicial de acceso",
    )
    return {
        "status": "request_created",
        "message": "Tu solicitud fue registrada y notificada a los administradores semilla.",
        "request_id": request_id,
    }


def _issue_otp(connection: Connection, settings: Settings, user: dict) -> dict:
    user_repo.invalidate_active_otps(connection, user["id"])
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = (datetime.now() + timedelta(minutes=OTP_VALID_MINUTES)).replace(microsecond=0).isoformat(sep=" ")
    resend_at = (datetime.now() + timedelta(seconds=OTP_RESEND_SECONDS)).replace(microsecond=0).isoformat(sep=" ")
    user_repo.create_otp(
        connection,
        user_id=user["id"],
        code_hash=_hash_code(code),
        expires_at=expires_at,
        resend_available_at=resend_at,
    )
    subject = "Codigo OTP para Grand Tower del Valle"
    body = (
        f"Hola {user['full_name']},\n\n"
        f"Tu codigo OTP es: {code}\n"
        f"Vigencia: {OTP_VALID_MINUTES} minutos.\n"
        f"Intentos maximos: {OTP_MAX_ATTEMPTS}.\n"
    )
    delivered, delivery_message = send_email(settings, to_email=user["email"], subject=subject, body=body)
    notification_repo.create_notification(
        connection,
        notification_type="otp",
        recipient_email=user["email"],
        recipient_user_id=user["id"],
        subject=subject,
        body_preview=f"OTP enviado con vigencia de {OTP_VALID_MINUTES} minutos",
        related_entity_type="user",
        related_entity_id=user["id"],
        status="enviada" if delivered else "fallida",
    )
    return {
        "status": "otp_sent" if delivered else "otp_failed",
        "message": "OTP enviado a tu correo." if delivered else f"No fue posible enviar el OTP: {delivery_message}",
    }


def verify_otp(
    connection: Connection,
    *,
    email: str,
    code: str,
) -> dict:
    normalized_email = email.strip().lower()
    user = user_repo.get_user_by_email(connection, normalized_email)
    if not user or user["status"] != "activo":
        return {"status": "error", "message": "Usuario no activo o inexistente."}

    otp = user_repo.get_active_otp(connection, user["id"])
    if not otp:
        return {"status": "error", "message": "No hay OTP vigente para este usuario."}
    if otp["expires_at"] <= _now():
        return {"status": "error", "message": "El OTP ya expiro."}

    if otp["code_hash"] != _hash_code(code.strip()):
        user_repo.increment_otp_attempts(connection, otp["id"])
        refreshed = user_repo.get_active_otp(connection, user["id"])
        attempts = refreshed["attempts_count"] if refreshed else OTP_MAX_ATTEMPTS
        remaining = max(0, OTP_MAX_ATTEMPTS - attempts)
        return {
            "status": "error",
            "message": f"OTP incorrecto. Intentos restantes: {remaining}.",
        }

    user_repo.consume_otp(connection, otp["id"])
    session_key = str(uuid4())
    login_at = _now()
    user_repo.create_session(connection, user_id=user["id"], session_key=session_key, login_at=login_at)
    auditing.audit_event(
        connection,
        user_email=user["email"],
        entity_type="session",
        entity_id=session_key,
        action="login",
        context="Inicio de sesion exitoso por OTP",
    )
    return {
        "status": "ok",
        "message": "Sesion iniciada correctamente.",
        "session_key": session_key,
        "user": _to_authenticated_user(user),
    }


def get_user_from_session(connection: Connection, session_key: str | None) -> AuthenticatedUser | None:
    if not session_key:
        return None
    session = user_repo.get_session(connection, session_key)
    if not session or session.get("logout_at"):
        return None
    user = user_repo.get_user_by_id(connection, session["user_id"])
    if not user or user["status"] != "activo":
        return None
    return _to_authenticated_user(user)


def touch_session(connection: Connection, session_key: str) -> None:
    user_repo.touch_session(connection, session_key, _now())


def logout(connection: Connection, *, session_key: str, user_email: str, reason: str) -> None:
    logout_at = _now()
    user_repo.close_session(connection, session_key, logout_at, reason)
    auditing.audit_event(
        connection,
        user_email=user_email,
        entity_type="session",
        entity_id=session_key,
        action="logout",
        context=reason,
    )


def approve_access_request(
    connection: Connection,
    settings: Settings,
    *,
    request_id: int,
    resolver_user: AuthenticatedUser,
    notes: str | None = None,
) -> None:
    resolved = user_repo.resolve_access_request(
        connection,
        request_id=request_id,
        resolver_user_id=resolver_user.id,
        approved=True,
        notes=notes,
    )
    if not resolved:
        return
    _notify_request_resolution(
        connection,
        settings,
        request_id=request_id,
        target_email=resolved["email"],
        approved=True,
    )
    auditing.audit_event(
        connection,
        user_email=resolver_user.email,
        entity_type="access_request",
        entity_id=str(request_id),
        action="aprobada",
        context=notes,
    )


def reject_access_request(
    connection: Connection,
    settings: Settings,
    *,
    request_id: int,
    resolver_user: AuthenticatedUser,
    notes: str | None = None,
) -> None:
    resolved = user_repo.resolve_access_request(
        connection,
        request_id=request_id,
        resolver_user_id=resolver_user.id,
        approved=False,
        notes=notes,
    )
    if not resolved:
        return
    _notify_request_resolution(
        connection,
        settings,
        request_id=request_id,
        target_email=resolved["email"],
        approved=False,
    )
    auditing.audit_event(
        connection,
        user_email=resolver_user.email,
        entity_type="access_request",
        entity_id=str(request_id),
        action="rechazada",
        context=notes,
    )


def _notify_seed_admins_of_access_request(
    connection: Connection,
    settings: Settings,
    *,
    requester_email: str,
    requester_name: str,
    requester_preferred_name: str,
    request_id: int,
) -> None:
    subject = "Nueva solicitud de acceso - Grand Tower del Valle"
    body = (
        f"Se recibio una nueva solicitud de acceso.\n\n"
        f"Solicitante: {requester_name}\n"
        f"Nombre preferido: {requester_preferred_name}\n"
        f"Correo: {requester_email}\n"
        f"Solicitud ID: {request_id}\n"
    )
    for admin in settings.seed_admins:
        delivered, _ = send_email(settings, to_email=admin.email, subject=subject, body=body)
        admin_user = user_repo.get_user_by_email(connection, admin.email)
        notification_repo.create_notification(
            connection,
            notification_type="access_request_pending",
            recipient_email=admin.email,
            recipient_user_id=admin_user["id"] if admin_user else None,
            subject=subject,
            body_preview=f"Solicitud #{request_id} de {requester_email}",
            related_entity_type="access_request",
            related_entity_id=request_id,
            status="enviada" if delivered else "fallida",
        )


def _notify_request_resolution(
    connection: Connection,
    settings: Settings,
    *,
    request_id: int,
    target_email: str,
    approved: bool,
) -> None:
    subject = "Resolucion de acceso - Grand Tower del Valle"
    body = (
        "Tu solicitud de acceso fue aprobada.\nYa puedes pedir un OTP para iniciar sesion."
        if approved
        else "Tu solicitud de acceso fue rechazada."
    )
    delivered, _ = send_email(settings, to_email=target_email, subject=subject, body=body)
    user = user_repo.get_user_by_email(connection, target_email)
    notification_repo.create_notification(
        connection,
        notification_type="access_request_resolved",
        recipient_email=target_email,
        recipient_user_id=user["id"] if user else None,
        subject=subject,
        body_preview=body,
        related_entity_type="access_request",
        related_entity_id=request_id,
        status="resuelta" if delivered else "fallida",
    )


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")
