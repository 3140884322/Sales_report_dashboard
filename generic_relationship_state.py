from __future__ import annotations

from collections.abc import MutableMapping, Sequence
import hashlib
from pathlib import Path
from typing import Any


GENERIC_RESULT_STATE_KEYS = (
    "generic_discovery_result",
    "generic_relationship_decisions",
    "generic_edited_candidates",
    "generic_editing_candidate_id",
    "generic_approved_plan",
    "generic_merge_result",
    "generic_plan_error",
    "generic_fact_table_id",
    "generic_fact_table_snapshot",
    "generic_mapping_signature",
    "generic_mapping_recommendations",
    "generic_standard_mapping_result",
    "generic_mapping_error",
    "generic_report_signature",
    "generic_report_result",
    "generic_report_error",
    "generic_report_confirm",
    "generic_report_date_action",
    "generic_report_exclude_critical",
)
GENERIC_DYNAMIC_WIDGET_PREFIXES = (
    "generic_candidate_",
    "generic_edit_",
    "generic_mapping_",
    "generic_report_",
)


def _file_bytes(source: Any) -> bytes:
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    original_position = None
    try:
        original_position = source.tell()
    except (AttributeError, OSError, ValueError):
        pass
    try:
        if hasattr(source, "getvalue"):
            data = source.getvalue()
        else:
            source.seek(0)
            data = source.read()
    finally:
        if original_position is not None:
            try:
                source.seek(original_position)
            except (AttributeError, OSError, ValueError):
                pass
    return data.encode("utf-8") if isinstance(data, str) else bytes(data)


def make_generic_upload_signature(uploaded_files: Sequence[Any]) -> tuple[tuple, ...]:
    """Create an order-sensitive signature for the complete generic upload set."""
    signature = []
    for source in uploaded_files:
        data = _file_bytes(source)
        signature.append(
            (
                str(getattr(source, "name", "uploaded")),
                len(data),
                hashlib.md5(data).hexdigest(),
            )
        )
    return tuple(signature)


def invalidate_generic_report_state(state: MutableMapping[str, Any]) -> None:
    """Clear B2.2 decisions and output while preserving an uploaded expense file."""
    for key in (
        "generic_report_signature",
        "generic_report_result",
        "generic_report_error",
        "generic_report_confirm",
        "generic_report_date_action",
        "generic_report_exclude_critical",
    ):
        state.pop(key, None)


def clear_generic_report_if_inputs_changed(
    state: MutableMapping[str, Any],
    report_signature: tuple,
) -> bool:
    """Invalidate a cached report only when mapping or expense inputs changed."""
    if state.get("generic_report_signature") == report_signature:
        return False
    state["generic_report_signature"] = report_signature
    for key in (
        "generic_report_result",
        "generic_report_error",
        "generic_report_confirm",
    ):
        state.pop(key, None)
    return True


def invalidate_generic_mapping_state(state: MutableMapping[str, Any]) -> None:
    """Clear B2.1 choices and output when its merged input becomes stale."""
    for key in (
        "generic_mapping_signature",
        "generic_mapping_recommendations",
        "generic_standard_mapping_result",
        "generic_mapping_error",
    ):
        state.pop(key, None)
    for key in list(state):
        if key.startswith("generic_mapping_"):
            state.pop(key, None)
    invalidate_generic_report_state(state)


def invalidate_generic_plan_state(state: MutableMapping[str, Any]) -> None:
    for key in ("generic_approved_plan", "generic_merge_result", "generic_plan_error"):
        state.pop(key, None)
    invalidate_generic_mapping_state(state)


def clear_generic_state_if_uploads_changed(
    state: MutableMapping[str, Any],
    upload_signature: tuple[tuple, ...],
) -> bool:
    """Clear discovery, decisions, plan, widgets, and merge output after file changes."""
    if state.get("generic_upload_signature") == upload_signature:
        return False

    state["generic_upload_signature"] = upload_signature
    for key in GENERIC_RESULT_STATE_KEYS:
        state.pop(key, None)
    for key in list(state):
        if key.startswith(GENERIC_DYNAMIC_WIDGET_PREFIXES):
            state.pop(key, None)
    return True
