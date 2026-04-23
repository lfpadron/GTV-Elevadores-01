"""Upload processing, file persistence and incident creation."""

from __future__ import annotations

from pathlib import Path
import shutil
from sqlite3 import Connection

from gtv.config import Settings
from gtv.constants import DOCUMENT_FOLDERS
from gtv.models import AuthenticatedUser
from gtv.repositories import documents as document_repo
from gtv.services import cases as case_service
from gtv.services.extractors import extract_document_structured
from gtv.services.pdf_reader import extract_pages_from_pdf
from gtv.utils.files import next_duplicate_name, sanitize_filename, sha256_bytes, split_filename


def process_uploaded_pdf(
    connection: Connection,
    settings: Settings,
    *,
    file_name: str,
    file_bytes: bytes,
    uploaded_by: AuthenticatedUser,
) -> dict:
    safe_name = sanitize_filename(file_name)
    pages = extract_pages_from_pdf(file_bytes)
    layout_pages = extract_pages_from_pdf(file_bytes, extraction_mode="layout")
    extracted = extract_document_structured(pages, file_name=safe_name, layout_pages=layout_pages)
    storage_root = _destination_root(settings, extracted.document_type)
    date_folder = _resolve_date_folder(settings, extracted.document_type, extracted.document_date)
    duplicate_matches = document_repo.find_existing_named_documents(
        connection,
        file_name_original=safe_name,
        target_folder_fragment=str(date_folder.relative_to(settings.data_dir)),
    )
    duplicate_of = duplicate_matches[0]["id"] if duplicate_matches else None
    duplicate_status = "pending_review" if duplicate_matches else "original"
    inclusion_status = "ignorado" if duplicate_matches else "incluido"

    if duplicate_matches:
        final_folder = _resolve_date_folder(settings, "duplicado", extracted.document_date)
        stored_file_name = safe_name
    else:
        final_folder = date_folder
        stored_file_name = safe_name

    final_folder.mkdir(parents=True, exist_ok=True)
    stored_path = final_folder / stored_file_name
    stored_path.write_bytes(file_bytes)

    position_id = document_repo.get_position_id(connection, extracted.position)
    document_id = document_repo.create_document(
        connection,
        {
            "document_type": extracted.document_type,
            "classification_source": "automatico",
            "extraction_status": extracted.extraction_status,
            "duplicate_status": duplicate_status,
            "document_status": "activo",
            "inclusion_status": inclusion_status,
            "file_name_original": safe_name,
            "file_name_stored": stored_file_name,
            "file_extension": split_filename(safe_name)[1] or ".pdf",
            "file_sha256": sha256_bytes(file_bytes),
            "storage_path": str(stored_path),
            "duplicate_of_document_id": duplicate_of,
            "uploaded_by_user_id": uploaded_by.id,
            "tower": extracted.tower,
            "position_id": position_id,
            "equipment_text_original": extracted.equipment_text,
            "equipment_code": extracted.equipment_code,
            "equipment_key": extracted.equipment_key,
            "document_date": extracted.document_date,
            "document_time": extracted.document_time,
            "primary_identifier": extracted.primary_identifier,
            "short_description": extracted.short_description,
            "summary_ai_original": extracted.summary_ai_original,
            "summary_user_edited": None,
            "raw_text": extracted.raw_text,
            "total_pages": extracted.total_pages,
        },
    )
    document_repo.insert_document_pages(
        connection,
        document_id=document_id,
        file_name=safe_name,
        document_type=extracted.document_type,
        pages=pages,
    )

    if extracted.document_type == "reporte":
        document_repo.upsert_fault_report(connection, document_id, extracted.detail_payload)
    elif extracted.document_type == "hallazgo":
        document_repo.upsert_finding(connection, document_id, extracted.detail_payload)
    elif extracted.document_type == "estimacion":
        document_repo.upsert_estimate(connection, document_id, extracted.detail_payload)
        document_repo.replace_estimate_items(connection, document_id, extracted.detail_payload.get("items", []))

    incidents: list[str] = []
    if extracted.document_type == "no_reconocido":
        document_repo.create_incident(
            connection,
            document_id=document_id,
            incident_type="tipo_no_reconocido",
            title="Documento no reconocido",
            details="El sistema no pudo clasificar el PDF y requiere clasificacion manual.",
        )
        incidents.append("tipo_no_reconocido")

    if duplicate_matches:
        document_repo.create_incident(
            connection,
            document_id=document_id,
            incident_type="duplicado_nombre",
            title="Posible duplicado por nombre de archivo",
            details=f"Se encontro un archivo previo con el mismo nombre. Documento previo ID: {duplicate_of}.",
        )
        incidents.append("duplicado_nombre")

    if extracted.extraction_status in {"parcial", "requiere_revision"}:
        document_repo.create_incident(
            connection,
            document_id=document_id,
            incident_type="extraccion_parcial" if extracted.extraction_status == "parcial" else "requiere_revision",
            title="Extraccion incompleta",
            details="Faltan campos criticos o requieren correccion manual.",
        )
        incidents.append("extraccion")

    document = document_repo.get_document(connection, document_id)
    if document and not duplicate_matches and extracted.document_type != "no_reconocido":
        suggestions = case_service.suggest_case_links_for_document(connection, document=document)
        if suggestions:
            document_repo.create_incident(
                connection,
                document_id=document_id,
                incident_type="vinculacion_pendiente",
                title="Documento pendiente de vinculacion",
                details="Se generaron sugerencias de caso y requieren confirmacion manual.",
            )
            incidents.append("vinculacion_pendiente")
        elif document.get("equipment_key"):
            case_service.create_case_from_document(
                connection,
                document=document,
                user_id=uploaded_by.id,
                origin="sistema_origen",
            )

    return {
        "document_id": document_id,
        "document_type": extracted.document_type,
        "extraction_status": extracted.extraction_status,
        "incidents": incidents,
        "stored_path": str(stored_path),
    }


def process_pdf_folder(
    connection: Connection,
    settings: Settings,
    *,
    folder_path: Path,
    uploaded_by: AuthenticatedUser,
) -> list[dict]:
    results: list[dict] = []
    for pdf_path in sorted(folder_path.rglob("*.pdf")):
        try:
            result = process_uploaded_pdf(
                connection,
                settings,
                file_name=pdf_path.name,
                file_bytes=pdf_path.read_bytes(),
                uploaded_by=uploaded_by,
            )
            results.append(result)
            pdf_path.unlink(missing_ok=True)
            _remove_empty_parent_dirs(pdf_path.parent, stop_at=folder_path)
        except Exception as exc:
            results.append(
                {
                    "document_id": None,
                    "document_type": "error",
                    "extraction_status": "fallo",
                    "incidents": [str(exc)],
                    "stored_path": "",
                    "source_file": str(pdf_path),
                }
            )
    return results


def keep_duplicate_document(
    connection: Connection,
    settings: Settings,
    *,
    document_id: int,
) -> dict:
    document = document_repo.get_document(connection, document_id)
    if not document:
        raise ValueError("Documento no encontrado")
    original_folder = _resolve_date_folder(settings, document["document_type"], document.get("document_date"))
    original_folder.mkdir(parents=True, exist_ok=True)
    base_name, extension = split_filename(document["file_name_original"])
    existing_names = [path.name for path in original_folder.glob(f"{base_name}*{extension}")]
    new_name = next_duplicate_name(base_name, extension, existing_names)
    destination = original_folder / new_name
    shutil.move(document["storage_path"], destination)
    document_repo.update_document_fields(
        connection,
        document_id,
        {
            "file_name_stored": new_name,
            "storage_path": str(destination),
            "duplicate_status": "kept_duplicate",
            "inclusion_status": "incluido",
            "document_status": "activo",
        },
    )
    return {"file_name_stored": new_name, "storage_path": str(destination)}


def discard_duplicate_document(connection: Connection, *, document_id: int) -> None:
    document_repo.update_document_fields(
        connection,
        document_id,
        {
            "duplicate_status": "discarded",
            "document_status": "descartado",
            "inclusion_status": "ignorado",
        },
    )


def reclassify_document(
    connection: Connection,
    settings: Settings,
    *,
    document_id: int,
    new_document_type: str,
) -> dict:
    document = document_repo.get_document(connection, document_id)
    if not document:
        raise ValueError("Documento no encontrado")
    file_bytes = Path(document["storage_path"]).read_bytes()
    pages = extract_pages_from_pdf(file_bytes)
    layout_pages = extract_pages_from_pdf(file_bytes, extraction_mode="layout")
    extracted = extract_document_structured(
        pages,
        file_name=document["file_name_original"],
        layout_pages=layout_pages,
        forced_document_type=new_document_type,
    )
    new_folder = _resolve_date_folder(settings, new_document_type, document.get("document_date"))
    new_folder.mkdir(parents=True, exist_ok=True)
    new_path = new_folder / document["file_name_stored"]
    shutil.move(document["storage_path"], new_path)
    position_id = document_repo.get_position_id(connection, extracted.position)
    document_repo.update_document_fields(
        connection,
        document_id,
        {
            "document_type": new_document_type,
            "classification_source": "manual",
            "storage_path": str(new_path),
            "tower": extracted.tower,
            "position_id": position_id,
            "equipment_text_original": extracted.equipment_text,
            "equipment_code": extracted.equipment_code,
            "equipment_key": extracted.equipment_key,
            "document_date": extracted.document_date,
            "document_time": extracted.document_time,
            "primary_identifier": extracted.primary_identifier,
            "short_description": extracted.short_description,
            "summary_ai_original": extracted.summary_ai_original,
            "raw_text": extracted.raw_text,
            "extraction_status": extracted.extraction_status,
        },
    )
    if new_document_type == "reporte":
        document_repo.upsert_fault_report(connection, document_id, extracted.detail_payload)
    elif new_document_type == "hallazgo":
        document_repo.upsert_finding(connection, document_id, extracted.detail_payload)
    elif new_document_type == "estimacion":
        document_repo.upsert_estimate(connection, document_id, extracted.detail_payload)
        document_repo.replace_estimate_items(connection, document_id, extracted.detail_payload.get("items", []))
    return {"document_type": new_document_type, "storage_path": str(new_path)}


def _destination_root(settings: Settings, document_type: str) -> Path:
    folder_name = DOCUMENT_FOLDERS.get(document_type, DOCUMENT_FOLDERS["duplicado"])
    return settings.data_dir / folder_name


def _resolve_date_folder(settings: Settings, document_type: str, document_date: str | None) -> Path:
    root = _destination_root(settings, document_type)
    if document_date:
        year, month, _day = document_date.split("-")
        return root / year / f"{year}-{month}"
    today = Path("sin_fecha")
    return root / today


def _remove_empty_parent_dirs(path: Path, *, stop_at: Path) -> None:
    current = path
    stop_resolved = stop_at.resolve()
    while True:
        current_resolved = current.resolve()
        if current_resolved == stop_resolved:
            break
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
