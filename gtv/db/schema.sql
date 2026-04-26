PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equipment_catalog (
    equipment_code TEXT PRIMARY KEY,
    tower TEXT NOT NULL,
    position_name TEXT,
    display_name TEXT NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equipment_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_text TEXT NOT NULL UNIQUE,
    normalized_alias TEXT NOT NULL UNIQUE,
    equipment_code TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'seed', 'documento')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (equipment_code) REFERENCES equipment_catalog (equipment_code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    preferred_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('semilla_admin', 'usuario')),
    status TEXT NOT NULL CHECK (status IN ('activo', 'pendiente_aprobacion', 'rechazado', 'deshabilitado')),
    is_seed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at TEXT,
    approved_by_user_id INTEGER,
    rejected_at TEXT,
    rejected_by_user_id INTEGER,
    last_login_at TEXT,
    last_logout_at TEXT,
    FOREIGN KEY (approved_by_user_id) REFERENCES users (id),
    FOREIGN KEY (rejected_by_user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS access_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    requested_name TEXT,
    requested_preferred_name TEXT,
    status TEXT NOT NULL DEFAULT 'pendiente' CHECK (status IN ('pendiente', 'aprobada', 'rechazada')),
    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    resolved_by_user_id INTEGER,
    resolution_notes TEXT,
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (resolved_by_user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    code_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    resend_available_at TEXT NOT NULL,
    attempts_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    consumed_at TEXT,
    invalidated_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    session_key TEXT NOT NULL UNIQUE,
    login_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    logout_at TEXT,
    logout_reason TEXT,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_type TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    recipient_user_id INTEGER,
    related_entity_type TEXT,
    related_entity_id INTEGER,
    subject TEXT NOT NULL,
    body_preview TEXT,
    status TEXT NOT NULL DEFAULT 'enviada' CHECK (status IN ('enviada', 'leida', 'resuelta', 'fallida')),
    sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TEXT,
    resolved_at TEXT,
    FOREIGN KEY (recipient_user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS case_daily_counters (
    counter_date TEXT PRIMARY KEY,
    last_value INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_type TEXT NOT NULL CHECK (document_type IN ('reporte', 'hallazgo', 'estimacion', 'ticket_usuario', 'no_reconocido')),
    classification_source TEXT NOT NULL DEFAULT 'automatico' CHECK (classification_source IN ('automatico', 'manual')),
    extraction_status TEXT NOT NULL CHECK (extraction_status IN ('ok', 'parcial', 'requiere_revision')),
    duplicate_status TEXT NOT NULL DEFAULT 'original' CHECK (duplicate_status IN ('original', 'pending_review', 'kept_duplicate', 'discarded')),
    document_status TEXT NOT NULL DEFAULT 'activo' CHECK (document_status IN ('activo', 'descartado')),
    inclusion_status TEXT NOT NULL DEFAULT 'incluido' CHECK (inclusion_status IN ('incluido', 'ignorado')),
    file_name_original TEXT NOT NULL,
    file_name_stored TEXT NOT NULL,
    file_extension TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    duplicate_of_document_id INTEGER,
    uploaded_by_user_id INTEGER,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    tower TEXT,
    position_id INTEGER,
    equipment_text_original TEXT,
    equipment_code TEXT,
    equipment_key TEXT,
    document_date TEXT,
    document_time TEXT,
    primary_identifier TEXT,
    short_description TEXT,
    summary_ai_original TEXT,
    summary_user_edited TEXT,
    raw_text TEXT NOT NULL,
    total_pages INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (duplicate_of_document_id) REFERENCES documents (id),
    FOREIGN KEY (uploaded_by_user_id) REFERENCES users (id),
    FOREIGN KEY (position_id) REFERENCES positions (id)
);

CREATE TABLE IF NOT EXISTS document_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    page_text TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
    UNIQUE (document_id, page_number)
);

CREATE VIRTUAL TABLE IF NOT EXISTS document_pages_fts
USING fts5(
    document_id UNINDEXED,
    page_number UNINDEXED,
    file_name,
    document_type,
    page_text
);

CREATE TABLE IF NOT EXISTS fault_reports (
    document_id INTEGER PRIMARY KEY,
    ticket_number TEXT,
    report_state TEXT NOT NULL DEFAULT 'reportado' CHECK (report_state IN ('reportado', 'en_atencion', 'cerrado')),
    description TEXT,
    cause_text TEXT,
    solution_text TEXT,
    source_pages TEXT,
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS findings (
    document_id INTEGER PRIMARY KEY,
    base_ticket_number TEXT,
    finding_folio TEXT,
    finding_state TEXT NOT NULL DEFAULT 'detectado' CHECK (finding_state IN ('detectado', 'en_revision', 'atendido', 'cerrado')),
    description TEXT,
    affected_part_text TEXT,
    recommendation_text TEXT,
    source_pages TEXT,
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS estimates (
    document_id INTEGER PRIMARY KEY,
    original_folio TEXT,
    normalized_folio TEXT,
    report_reference_text TEXT,
    finding_reference_text TEXT,
    missing_supporting_reference INTEGER NOT NULL DEFAULT 0,
    estimate_state TEXT NOT NULL DEFAULT 'abierta' CHECK (estimate_state IN ('abierta', 'aprobada', 'pagada_parcial', 'pagada_total', 'en_surtimiento', 'parcialmente_recibida', 'completada', 'cancelada')),
    delivery_days INTEGER,
    estimated_delivery_date TEXT,
    subtotal_amount REAL,
    tax_amount REAL,
    total_amount REAL,
    source_pages TEXT,
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS estimate_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    estimate_document_id INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    concept_text TEXT NOT NULL,
    equipment_text_original TEXT,
    equipment_code TEXT,
    report_reference_text TEXT,
    finding_reference_text TEXT,
    report_document_id INTEGER,
    finding_document_id INTEGER,
    user_ticket_id INTEGER,
    delivery_days INTEGER,
    estimated_delivery_date TEXT,
    missing_catalog_equipment INTEGER NOT NULL DEFAULT 0,
    missing_supporting_reference INTEGER NOT NULL DEFAULT 0,
    quantity REAL NOT NULL DEFAULT 0,
    unit_price REAL NOT NULL DEFAULT 0,
    subtotal REAL NOT NULL DEFAULT 0,
    receipt_status TEXT NOT NULL DEFAULT 'no_recibida' CHECK (receipt_status IN ('no_recibida', 'parcialmente_recibida', 'recibida_total')),
    payment_status TEXT NOT NULL DEFAULT 'no_pagada' CHECK (payment_status IN ('no_pagada', 'pagada_parcial', 'pagada_total')),
    reception_date TEXT,
    payment_date TEXT,
    payment_method TEXT,
    invoice_date TEXT,
    invoice_number TEXT,
    notes TEXT,
    FOREIGN KEY (estimate_document_id) REFERENCES estimates (document_id) ON DELETE CASCADE,
    FOREIGN KEY (report_document_id) REFERENCES documents (id),
    FOREIGN KEY (finding_document_id) REFERENCES documents (id)
);

CREATE TABLE IF NOT EXISTS estimate_item_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    estimate_item_id INTEGER NOT NULL,
    unit_index INTEGER NOT NULL,
    receipt_status TEXT NOT NULL DEFAULT 'no_recibida' CHECK (receipt_status IN ('no_recibida', 'recibida_total')),
    reception_date TEXT,
    payment_status TEXT NOT NULL DEFAULT 'no_pagada' CHECK (payment_status IN ('no_pagada', 'pagada_total')),
    payment_date TEXT,
    payment_method TEXT,
    invoice_date TEXT,
    invoice_number TEXT,
    notes TEXT,
    FOREIGN KEY (estimate_item_id) REFERENCES estimate_items (id) ON DELETE CASCADE,
    UNIQUE (estimate_item_id, unit_index)
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_folio TEXT NOT NULL UNIQUE,
    equipment_key TEXT NOT NULL,
    tower TEXT,
    position_id INTEGER,
    equipment_text_original TEXT,
    origin_document_id INTEGER,
    anchor_date TEXT,
    suggested_consolidated_status TEXT,
    manual_consolidated_status TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by_user_id INTEGER,
    FOREIGN KEY (position_id) REFERENCES positions (id),
    FOREIGN KEY (origin_document_id) REFERENCES documents (id),
    FOREIGN KEY (created_by_user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS user_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_folio TEXT NOT NULL UNIQUE,
    document_date TEXT NOT NULL,
    document_time TEXT,
    tower TEXT,
    equipment_code TEXT,
    equipment_text_original TEXT,
    description TEXT NOT NULL,
    ticket_state TEXT NOT NULL DEFAULT 'abierto' CHECK (ticket_state IN ('abierto', 'en_revision', 'cerrado')),
    observations TEXT,
    source_document_id INTEGER,
    original_report_reference TEXT,
    original_finding_reference TEXT,
    original_estimate_reference TEXT,
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_document_id) REFERENCES documents (id),
    FOREIGN KEY (created_by_user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS case_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    document_id INTEGER NOT NULL UNIQUE,
    link_status TEXT NOT NULL CHECK (link_status IN ('sugerida', 'confirmada_manual', 'sin_vincular')),
    linked_by_user_id INTEGER,
    linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    origin TEXT NOT NULL DEFAULT 'manual',
    notes TEXT,
    FOREIGN KEY (case_id) REFERENCES cases (id) ON DELETE CASCADE,
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
    FOREIGN KEY (linked_by_user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS case_user_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    user_ticket_id INTEGER NOT NULL UNIQUE,
    linked_by_user_id INTEGER,
    linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    FOREIGN KEY (case_id) REFERENCES cases (id) ON DELETE CASCADE,
    FOREIGN KEY (user_ticket_id) REFERENCES user_tickets (id) ON DELETE CASCADE,
    FOREIGN KEY (linked_by_user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS case_link_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    case_id INTEGER NOT NULL,
    days_difference INTEGER NOT NULL,
    proximity_label TEXT NOT NULL,
    link_status TEXT NOT NULL DEFAULT 'sugerida' CHECK (link_status IN ('sugerida', 'confirmada_manual', 'descartada')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at TEXT,
    decided_by_user_id INTEGER,
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
    FOREIGN KEY (case_id) REFERENCES cases (id) ON DELETE CASCADE,
    FOREIGN KEY (decided_by_user_id) REFERENCES users (id),
    UNIQUE (document_id, case_id)
);

CREATE TABLE IF NOT EXISTS finding_estimate_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    finding_document_id INTEGER,
    estimate_item_id INTEGER,
    finding_text_original TEXT,
    concept_text_original TEXT,
    score INTEGER NOT NULL DEFAULT 0,
    match_state TEXT NOT NULL CHECK (match_state IN ('confirmada', 'sugerida', 'sin_match', 'cotizada_sin_hallazgo')),
    confirmed_by_user_id INTEGER,
    confirmed_at TEXT,
    notes TEXT,
    FOREIGN KEY (case_id) REFERENCES cases (id) ON DELETE CASCADE,
    FOREIGN KEY (finding_document_id) REFERENCES findings (document_id) ON DELETE CASCADE,
    FOREIGN KEY (estimate_item_id) REFERENCES estimate_items (id) ON DELETE CASCADE,
    FOREIGN KEY (confirmed_by_user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER,
    incident_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendiente' CHECK (status IN ('pendiente', 'resuelta', 'descartada')),
    title TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    resolved_by_user_id INTEGER,
    resolution_notes TEXT,
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
    FOREIGN KEY (resolved_by_user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    event_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    context TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_type_date ON documents (document_type, document_date);
CREATE INDEX IF NOT EXISTS idx_documents_identifier ON documents (primary_identifier);
CREATE INDEX IF NOT EXISTS idx_documents_equipment ON documents (equipment_key, document_date);
CREATE INDEX IF NOT EXISTS idx_documents_equipment_code ON documents (equipment_code, document_date);
CREATE INDEX IF NOT EXISTS idx_equipment_catalog_tower ON equipment_catalog (tower, is_active);
CREATE INDEX IF NOT EXISTS idx_equipment_aliases_code ON equipment_aliases (equipment_code, normalized_alias);
CREATE INDEX IF NOT EXISTS idx_estimate_items_equipment_code ON estimate_items (equipment_code, estimated_delivery_date);
CREATE INDEX IF NOT EXISTS idx_estimate_items_support_flags ON estimate_items (missing_catalog_equipment, missing_supporting_reference);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents (status, incident_type);
CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications (status, recipient_email);
CREATE INDEX IF NOT EXISTS idx_case_suggestions_document ON case_link_suggestions (document_id, link_status);
CREATE INDEX IF NOT EXISTS idx_audit_logs_event_at ON audit_logs (event_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_tickets_date ON user_tickets (document_date DESC, ticket_state);
