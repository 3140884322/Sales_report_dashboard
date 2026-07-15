from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook

from relationship_models import LoadedTable


ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "cp1252", "latin1")
SUPPORTED_SUFFIXES = {".csv", ".xlsx"}


class GenericTableReaderError(ValueError):
    """Raised when a generic tabular source cannot be read safely."""


def _is_file_like(source: Any) -> bool:
    return hasattr(source, "read") or hasattr(source, "getvalue")


def _source_name(source: Any) -> str:
    if isinstance(source, (str, Path)):
        return Path(source).name
    return str(getattr(source, "name", "uploaded"))


def _read_source_bytes(source: Any) -> bytes:
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()

    if not _is_file_like(source):
        raise GenericTableReaderError(
            "A source must be a file path or a binary/text file-like object."
        )

    original_position = None
    try:
        original_position = source.tell()
    except (AttributeError, OSError, ValueError):
        pass

    try:
        if hasattr(source, "getvalue"):
            data = source.getvalue()
        else:
            try:
                source.seek(0)
            except (AttributeError, OSError, ValueError):
                pass
            data = source.read()
    finally:
        if original_position is not None:
            try:
                source.seek(original_position)
            except (AttributeError, OSError, ValueError):
                pass

    if isinstance(data, str):
        return data.encode("utf-8")
    if not isinstance(data, (bytes, bytearray)):
        raise GenericTableReaderError("The file-like source did not return bytes or text.")
    return bytes(data)


def _read_csv(data: bytes, source_name: str) -> tuple[pd.DataFrame, str]:
    last_error = None
    for encoding in ENCODING_CANDIDATES:
        try:
            frame = pd.read_csv(BytesIO(data), encoding=encoding)
            if len(frame.columns) == 1:
                sample = data[:8192].decode(encoding)
                try:
                    delimiter = csv.Sniffer().sniff(
                        sample, delimiters=",;|\t"
                    ).delimiter
                except csv.Error:
                    delimiter = ","
                if delimiter != ",":
                    frame = pd.read_csv(
                        BytesIO(data), encoding=encoding, sep=delimiter
                    )
            return frame, encoding
        except UnicodeDecodeError as error:
            last_error = error

    raise GenericTableReaderError(
        f"Could not decode {source_name}. Tried {', '.join(ENCODING_CANDIDATES)}. "
        f"Last error: {last_error}"
    )


def _read_xlsx(data: bytes, source_name: str) -> dict[str, pd.DataFrame]:
    try:
        workbook = load_workbook(BytesIO(data), read_only=False, data_only=True)
    except Exception as error:
        raise GenericTableReaderError(f"Could not open workbook {source_name}: {error}") from error

    try:
        merged_sheets = [
            sheet.title for sheet in workbook.worksheets if sheet.merged_cells.ranges
        ]
    finally:
        workbook.close()

    if merged_sheets:
        names = ", ".join(merged_sheets)
        raise GenericTableReaderError(
            f"Workbook {source_name} contains merged cells in sheet(s): {names}. "
            "Relationship Discovery v1 supports ordinary first-row headers only."
        )

    try:
        return pd.read_excel(
            BytesIO(data), sheet_name=None, header=0, engine="openpyxl"
        )
    except Exception as error:
        raise GenericTableReaderError(f"Could not read workbook {source_name}: {error}") from error


def _iter_named_sources(sources: Any) -> list[tuple[str | None, Any]]:
    if isinstance(sources, Mapping):
        return [(str(name), source) for name, source in sources.items()]
    if isinstance(sources, (str, Path)) or _is_file_like(sources):
        return [(None, sources)]
    if isinstance(sources, Sequence):
        return [(None, source) for source in sources]
    raise GenericTableReaderError(
        "Sources must be one path/file-like object, a sequence, or a name-to-source mapping."
    )


def _unique_table_id(base_id: str, used_ids: set[str]) -> str:
    candidate = base_id
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base_id}#{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def read_tabular_sources(sources: Any) -> list[LoadedTable]:
    """Read CSV/xlsx paths or file-like objects; each workbook sheet is a table."""
    loaded: list[LoadedTable] = []
    used_ids: set[str] = set()

    for logical_name, source in _iter_named_sources(sources):
        source_name = _source_name(source)
        data = _read_source_bytes(source)
        suffix = Path(source_name).suffix.lower()
        if not suffix:
            suffix = ".xlsx" if data.startswith(b"PK\x03\x04") else ".csv"
        if suffix not in SUPPORTED_SUFFIXES:
            raise GenericTableReaderError(
                f"Unsupported source {source_name!r}. Supported formats: CSV and xlsx."
            )

        base_name = logical_name or Path(source_name).stem

        if suffix == ".csv":
            frame, encoding = _read_csv(data, source_name)
            table_id = _unique_table_id(base_name, used_ids)
            loaded.append(
                LoadedTable(
                    table_id=table_id,
                    table_name=base_name,
                    source_name=source_name,
                    frame=frame,
                    encoding=encoding,
                )
            )
            continue

        sheets = _read_xlsx(data, source_name)
        for sheet_name, frame in sheets.items():
            table_id = _unique_table_id(f"{base_name}::{sheet_name}", used_ids)
            loaded.append(
                LoadedTable(
                    table_id=table_id,
                    table_name=str(sheet_name),
                    source_name=source_name,
                    sheet_name=str(sheet_name),
                    frame=frame,
                )
            )

    return loaded
