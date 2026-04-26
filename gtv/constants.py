"""Shared application constants."""

from __future__ import annotations

DOCUMENT_TYPES = {
    "reporte": "Reporte de Fallas",
    "hallazgo": "Reporte de Hallazgo",
    "estimacion": "Estimacion",
    "ticket_usuario": "Ticket Usuario",
    "no_reconocido": "No reconocido",
}

DOCUMENT_FOLDERS = {
    "reporte": "reportes",
    "hallazgo": "hallazgos",
    "estimacion": "estimaciones",
    "ticket_usuario": "tickets_usuario",
    "no_reconocido": "no_reconocidos",
    "duplicado": "duplicados",
    "exporte": "exportes",
}

LINK_VISUAL_LABELS = {
    "muy_cercana": "0 a 3 dias",
    "cercana": "4 a 7 dias",
    "posible": "8 a 15 dias",
}

POSITION_DEFAULTS = ["izquierdo", "derecho", "servicio", "carga", "unico"]

USER_STATUSES = ["activo", "pendiente_aprobacion", "rechazado", "deshabilitado"]
USER_ROLES = ["semilla_admin", "usuario"]

OTP_VALID_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 60

EXTRACTION_STATUSES = ["ok", "parcial", "requiere_revision"]
LINK_STATUSES = ["sugerida", "confirmada_manual", "sin_vincular"]

REPORT_STATES = ["reportado", "en_atencion", "cerrado"]
FINDING_STATES = ["detectado", "en_revision", "atendido", "cerrado"]
ESTIMATE_STATES = [
    "abierta",
    "aprobada",
    "pagada_parcial",
    "pagada_total",
    "en_surtimiento",
    "parcialmente_recibida",
    "completada",
    "cancelada",
]

UNIT_RECEIPT_STATES = ["no_recibida", "recibida_total"]
ITEM_RECEIPT_STATES = ["no_recibida", "parcialmente_recibida", "recibida_total"]
UNIT_PAYMENT_STATES = ["no_pagada", "pagada_total"]
ITEM_PAYMENT_STATES = ["no_pagada", "pagada_parcial", "pagada_total"]

MATCH_STATES = ["confirmada", "sugerida", "sin_match", "cotizada_sin_hallazgo"]

ESTIMATE_RULES_EFFECTIVE_DATE = "2026-04-26"

INCIDENT_TYPES = [
    "tipo_no_reconocido",
    "duplicado_nombre",
    "extraccion_parcial",
    "requiere_revision",
    "vinculacion_pendiente",
]

CASE_STATUS_PRESETS = [
    "pendiente_documentacion",
    "pendiente_revision",
    "en_gestion",
    "pendiente_compra",
    "pendiente_recepcion",
    "cerrado",
]

USER_TICKET_STATES = ["abierto", "en_revision", "cerrado"]
