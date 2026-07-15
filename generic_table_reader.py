from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
from io import BytesIO
from pathlib import Path
import re
from typing import Any
import unicodedata

import pandas as pd
from openpyxl import load_workbook

from relationship_models import LoadedTable


ENCODING_CANDIDATES = (
    "utf-8-sig",
    "utf-8",
    "gb18030",
    "gbk",
    "cp1252",
    "latin1",
)
SUPPORTED_SUFFIXES = {".csv", ".xlsx"}
MOJIBAKE_UI_MESSAGE_KEY = "reader.encoding_error"
MOJIBAKE_ENGLISH_MESSAGE = (
    "The file may use an unsupported encoding or was decoded as unreadable text. "
    "Try saving the CSV as UTF-8 or uploading it as XLSX."
)
MOJIBAKE_THRESHOLD = 0.55
_SUSPICIOUS_MOJIBAKE_CHARS = frozenset(
    "ÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ"
    "ØÙÚÛÜÝÞæðñþ±º»¼½¾"
)
_COMMON_MOJIBAKE_SEQUENCES = (
    "Ã ", "Ã¡", "Ã©", "Ã­", "Ã³", "Ãº", "Â ", "ï¿½",
    "éÌ", "Æ·", "±à", "ºÅ", "éÆ·", "锟斤拷",
)


class GenericTableReaderError(ValueError):
    """Raised when a generic tabular source cannot be read safely."""

    def __init__(self, message: str, ui_message_key: str | None = None):
        self.ui_message_key = ui_message_key
        super().__init__(message)


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


def _sample_frame_text(frame: pd.DataFrame, maximum_values: int = 60) -> list[str]:
    samples = [str(column) for column in frame.columns]
    remaining = maximum_values
    for column in frame.columns:
        if remaining <= 0:
            break
        series = frame[column]
        if not (
            pd.api.types.is_object_dtype(series.dtype)
            or pd.api.types.is_string_dtype(series.dtype)
        ):
            continue
        values = series.dropna().astype("string").drop_duplicates().head(8)
        samples.extend(str(value) for value in values)
        remaining -= len(values)
    return samples


def mojibake_score(frame: pd.DataFrame) -> float:
    """Conservatively score unreadable decoded text using headers and small samples."""
    samples = _sample_frame_text(frame)
    text = " ".join(samples)
    if not text:
        return 0.0

    characters = [character for character in text if not character.isspace()]
    total = max(1, len(characters))
    replacement_count = text.count("�")
    control_count = sum(
        unicodedata.category(character) == "Cc" and character not in "\t\r\n"
        for character in text
    )
    suspicious_count = sum(
        character in _SUSPICIOUS_MOJIBAKE_CHARS for character in text
    )
    sequence_count = sum(text.casefold().count(sequence.casefold()) for sequence in _COMMON_MOJIBAKE_SEQUENCES)
    suspicious_runs = len(
        re.findall(r"[¡-ÿ]{4,}", text)
    )

    score = 0.0
    if replacement_count:
        score += min(1.0, replacement_count / total * 20.0)
    if control_count:
        score += min(0.8, control_count / total * 20.0)
    if suspicious_count >= 4:
        score += min(0.65, suspicious_count / total * 2.5)
    if sequence_count >= 2:
        score += min(0.7, sequence_count * 0.12)
    if suspicious_runs >= 2:
        score += min(0.5, suspicious_runs * 0.12)
    return round(min(1.0, score), 4)


def looks_like_mojibake(frame: pd.DataFrame) -> bool:
    return mojibake_score(frame) >= MOJIBAKE_THRESHOLD


def _parse_csv(data: bytes, encoding: str) -> pd.DataFrame:
    frame = pd.read_csv(BytesIO(data), encoding=encoding)
    if len(frame.columns) != 1:
        return frame

    sample = data[:8192].decode(encoding)
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;|\t").delimiter
    except csv.Error:
        delimiter = ","
    if delimiter == ",":
        return frame
    return pd.read_csv(BytesIO(data), encoding=encoding, sep=delimiter)


def _read_csv(data: bytes, source_name: str) -> tuple[pd.DataFrame, str]:
    last_error = None
    rejected_encodings: list[tuple[str, float]] = []
    for encoding in ENCODING_CANDIDATES:
        try:
            frame = _parse_csv(data, encoding)
            score = mojibake_score(frame)
            if score >= MOJIBAKE_THRESHOLD:
                rejected_encodings.append((encoding, score))
                if encoding in {"utf-8-sig", "utf-8"}:
                    raise GenericTableReaderError(
                        f"{MOJIBAKE_ENGLISH_MESSAGE} UTF-8 content had a "
                        f"mojibake score of {score:.2f}.",
                        ui_message_key=MOJIBAKE_UI_MESSAGE_KEY,
                    )
                continue
            detected_encoding = (
                "utf-8"
                if encoding == "utf-8-sig" and not data.startswith(b"\xef\xbb\xbf")
                else encoding
            )
            return frame, detected_encoding
        except GenericTableReaderError:
            raise
        except (UnicodeDecodeError, pd.errors.ParserError) as error:
            last_error = error

    if rejected_encodings:
        details = ", ".join(
            f"{encoding} (mojibake score {score:.2f})"
            for encoding, score in rejected_encodings
        )
        raise GenericTableReaderError(
            f"{MOJIBAKE_ENGLISH_MESSAGE} Rejected decoding attempts: {details}.",
            ui_message_key=MOJIBAKE_UI_MESSAGE_KEY,
        )
    raise GenericTableReaderError(
        f"Could not decode {source_name}. Tried {', '.join(ENCODING_CANDIDATES)}. "
        f"Last error: {last_error}. {MOJIBAKE_ENGLISH_MESSAGE}",
        ui_message_key=MOJIBAKE_UI_MESSAGE_KEY,
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
