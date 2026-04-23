"""Assisted matching between hallazgo pieces and estimate concepts."""

from __future__ import annotations

from sqlite3 import Connection

from rapidfuzz import fuzz

from gtv.repositories import documents as document_repo
from gtv.services.classifiers import similarity_label
from gtv.utils.text import normalize_for_match


def refresh_case_matches(connection: Connection, case_id: int) -> list[dict]:
    document_repo.delete_system_matches(connection, case_id)
    findings = document_repo.list_findings_for_case(connection, case_id)
    estimate_items = document_repo.list_estimate_items_for_case(connection, case_id)

    matched_item_ids: set[int] = set()
    for finding in findings:
        source_text = " ".join(
            part
            for part in [
                finding.get("affected_part_text"),
                finding.get("recommendation_text"),
                finding.get("description"),
            ]
            if part
        )
        normalized_source = normalize_for_match(source_text)
        best_item = None
        best_score = -1
        for item in estimate_items:
            candidate = normalize_for_match(item.get("concept_text"))
            if not normalized_source or not candidate:
                continue
            score = int(fuzz.token_sort_ratio(normalized_source, candidate))
            if score > best_score:
                best_score = score
                best_item = item
        if best_item and best_score >= 50:
            matched_item_ids.add(best_item["id"])
            document_repo.create_match(
                connection,
                {
                    "case_id": case_id,
                    "finding_document_id": finding["document_id"],
                    "estimate_item_id": best_item["id"],
                    "finding_text_original": source_text,
                    "concept_text_original": best_item["concept_text"],
                    "score": best_score,
                    "match_state": "sugerida",
                    "notes": similarity_label(best_score),
                },
            )
        else:
            document_repo.create_match(
                connection,
                {
                    "case_id": case_id,
                    "finding_document_id": finding["document_id"],
                    "estimate_item_id": None,
                    "finding_text_original": source_text,
                    "concept_text_original": None,
                    "score": max(best_score, 0),
                    "match_state": "sin_match",
                    "notes": "Hallazgo sin match automatico",
                },
            )

    for item in estimate_items:
        if item["id"] in matched_item_ids:
            continue
        document_repo.create_match(
            connection,
            {
                "case_id": case_id,
                "finding_document_id": None,
                "estimate_item_id": item["id"],
                "finding_text_original": None,
                "concept_text_original": item["concept_text"],
                "score": 0,
                "match_state": "cotizada_sin_hallazgo",
                "notes": "Concepto cotizado sin hallazgo asociado",
            },
        )
    return document_repo.list_matches_for_case(connection, case_id)


def confirm_match(connection: Connection, *, match_id: int, user_id: int) -> None:
    connection.execute(
        """
        UPDATE finding_estimate_matches
        SET match_state = 'confirmada',
            confirmed_by_user_id = ?,
            confirmed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (user_id, match_id),
    )


def mark_match_state(connection: Connection, *, match_id: int, state: str, user_id: int) -> None:
    connection.execute(
        """
        UPDATE finding_estimate_matches
        SET match_state = ?,
            confirmed_by_user_id = ?,
            confirmed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (state, user_id, match_id),
    )


def create_manual_match(
    connection: Connection,
    *,
    case_id: int,
    finding_document_id: int,
    estimate_item_id: int,
    user_id: int,
) -> None:
    finding_row = connection.execute(
        """
        SELECT affected_part_text, recommendation_text, description
        FROM findings
        WHERE document_id = ?
        """,
        (finding_document_id,),
    ).fetchone()
    item_row = connection.execute(
        "SELECT concept_text FROM estimate_items WHERE id = ?",
        (estimate_item_id,),
    ).fetchone()
    if not finding_row or not item_row:
        raise ValueError("Datos insuficientes para crear el match manual")

    source_text = " ".join(
        part
        for part in [
            finding_row["affected_part_text"],
            finding_row["recommendation_text"],
            finding_row["description"],
        ]
        if part
    )
    concept_text = item_row["concept_text"]
    score = int(fuzz.token_sort_ratio(normalize_for_match(source_text), normalize_for_match(concept_text)))
    connection.execute(
        """
        DELETE FROM finding_estimate_matches
        WHERE case_id = ?
          AND (finding_document_id = ? OR estimate_item_id = ?)
        """,
        (case_id, finding_document_id, estimate_item_id),
    )
    document_repo.create_match(
        connection,
        {
            "case_id": case_id,
            "finding_document_id": finding_document_id,
            "estimate_item_id": estimate_item_id,
            "finding_text_original": source_text,
            "concept_text_original": concept_text,
            "score": score,
            "match_state": "confirmada",
            "confirmed_by_user_id": user_id,
            "confirmed_at": connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0],
            "notes": "Match manual confirmado por usuario",
        },
    )
