"""Bounded structural inspection of a research file named by the user."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import zipfile
from pathlib import Path

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_EXPANDED_BYTES = 150 * 1024 * 1024
SUPPORTED = {".csv", ".tsv", ".txt", ".ras", ".xlsx", ".xlsm"}
NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
READ_DENIAL = re.compile(r"(?:不要|禁止|不得|不许|切勿|撤销).{0,12}(?:读取|访问|打开|检查|分析文件|文件访问)|(?:不允许|禁止).{0,8}文件(?:读取|访问)", re.I)


def authorized_file(path, user_text):
    """Only inspect a specific absolute path explicitly supplied in this turn."""
    if not isinstance(path, str) or not path.strip() or len(path) > 1200:
        raise ValueError("请提供用户本轮明确指定的完整文件路径。")
    if READ_DENIAL.search(str(user_text)):
        raise PermissionError("用户已限制本次文件读取。")
    original = Path(path)
    needle = path.replace("\\", "/").casefold()
    text = str(user_text).replace("\\", "/").casefold()
    positions = [m.start() for m in re.finditer(re.escape(needle), text)]
    mentioned = any(
        (end == len(text) or not (text[end].isascii() and (text[end].isalnum() or text[end] in "_-/")))
        and not (end + 1 < len(text) and text[end] == "." and text[end + 1].isalnum())
        for end in (start + len(needle) for start in positions)
    )
    if not original.is_absolute() or not mentioned:
        raise PermissionError("只能检查用户在本轮明确提供的绝对文件路径。")
    if original.is_symlink():
        raise ValueError("不支持符号链接文件；请提供真实文件路径。")
    resolved = original.resolve(strict=True)
    if not resolved.is_file() or resolved.suffix.casefold() not in SUPPORTED:
        raise ValueError("仅支持本地 CSV、TSV、TXT、RAS 和 Excel 数据文件。")
    if resolved.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("文件超过结构检查的 25 MB 上限。")
    return resolved


def _labels(row, row_number):
    # A mixed row may be a measurement row with sample identifiers; never
    # forward its text values as supposedly descriptive headers.
    if any(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        or isinstance(value, str) and bool(NUMBER.fullmatch(value.strip()))
        for value in row
        if value is not None
    ):
        return []
    labels = []
    for col, value in enumerate(row, 1):
        if isinstance(value, str):
            text = value.strip()
            if text and len(text) <= 100 and not NUMBER.fullmatch(text):
                labels.append({"row": row_number, "column": col, "label": text})
    return labels


def inspect_file(path):
    """Return format, file hash and structural metadata; omit numeric rows."""
    path = Path(path)
    raw = path.read_bytes()
    result = {
        "name": path.name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "format": path.suffix.lower(),
        "note": "只报告结构和开头的文本候选标签；候选标签可能并非表头，应核实。未返回数值数据行。",
    }
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > MAX_EXPANDED_BYTES:
                raise ValueError("工作簿解压后超过结构检查限制。")
        import openpyxl

        book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            result["sheets"] = []
            for sheet in book.worksheets[:20]:
                labels = []
                used_columns = set()
                text_positions = {}
                numeric_columns = set()
                numeric_positions = {}
                header_map = {}
                observed_rows = min(sheet.max_row or 0, 1000)
                for row_number, row in enumerate(sheet.iter_rows(min_row=1, max_row=max(observed_rows, 1), max_col=min(sheet.max_column or 1, 512), values_only=True), 1):
                    if row_number <= 2:
                        row_labels = _labels(row, row_number)
                        labels.extend(row_labels[:35])
                        header_map.update({item["column"]: item["label"] for item in row_labels})
                    used_columns.update(index for index, value in enumerate(row, 1) if value is not None and value != "")
                    for column, value in enumerate(row, 1):
                        number = isinstance(value, (int, float)) and not isinstance(value, bool)
                        numeric_text = isinstance(value, str) and bool(NUMBER.fullmatch(value.strip()))
                        if (number or numeric_text) and math.isfinite(float(value)):
                            numeric_positions.setdefault(column, set()).add(row_number)
                    if row_number >= 3:
                        for column, value in enumerate(row, 1):
                            if isinstance(value, str) and value.strip() and not NUMBER.fullmatch(value.strip()):
                                text_positions.setdefault(column, []).append(row_number)
                            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                                numeric_columns.add(column)
                sparse = []
                for column, positions in text_positions.items():
                    if column in numeric_columns or not 2 <= len(positions) <= 50 or len(positions) * 4 >= max(observed_rows - 2, 1):
                        continue
                    gaps = [b - a for a, b in zip(positions, positions[1:])]
                    sparse.append({
                        "column": column,
                        "nonempty_text_cells": len(positions),
                        "rows": positions,
                        "uniform_spacing": gaps[0] if gaps and len(set(gaps)) == 1 else None,
                    })
                pairs = []
                for column, positions in numeric_positions.items():
                    shared = positions & numeric_positions.get(column + 1, set())
                    if len(shared) < 2:
                        continue
                    first, last = min(shared), max(shared)
                    pairs.append({
                        "columns": [column, column + 1],
                        "candidate_headers": [header_map.get(column), header_map.get(column + 1)],
                        "paired_finite_rows": len(shared),
                        "first_row": first,
                        "last_row": last,
                        "contiguous": last - first + 1 == len(shared),
                    })
                pairs.sort(key=lambda pair: (-pair["paired_finite_rows"], pair["columns"][0]))
                result["sheets"].append({
                    "name": sheet.title,
                    "rows": sheet.max_row,
                    "columns": sheet.max_column,
                    "observed_rows_for_used_columns": observed_rows,
                    "observed_nonempty_columns": len(used_columns),
                    "observed_last_nonempty_column": max(used_columns, default=0),
                    "sparse_text_columns_after_first_two_rows": sparse[:20],
                    "adjacent_numeric_pairs": pairs[:8],
                    "pair_note": "仅说明相邻列数值覆盖；物理含义须依据候选表头和来源核实，不能自动认定为横轴/信号。",
                    "first_two_rows_text_labels": labels,
                    "labels_may_be_truncated": True,
                })
        finally:
            book.close()
        return result

    for encoding in ("utf-8-sig", "gb18030", "shift_jis"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("无法识别文本编码。")
    try:
        delimiter = " " if path.suffix.lower() == ".ras" else csv.Sniffer().sniff(text[:65536], delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    result.update(encoding=encoding, delimiter=delimiter, rows=len(rows))
    result["first_row_text_labels"] = _labels(rows[0], 1)[:100] if rows else []
    blocks, start, width = [], None, None
    for index, row in enumerate(rows + [[]], 1):
        values = [v.strip() for v in row if v.strip()]
        numeric = len(values) >= 2 and all(NUMBER.fullmatch(v) for v in values)
        if numeric and (start is None or len(values) == width):
            if start is None:
                start, width = index, len(values)
        else:
            if start is not None and index - start >= 2:
                blocks.append({"start_row": start, "end_row": index - 1, "nonempty_numeric_cells_per_row": width})
            start, width = (index, len(values)) if numeric else (None, None)
    result["numeric_blocks"] = sorted(blocks, key=lambda b: b["end_row"] - b["start_row"], reverse=True)[:5]
    result["numeric_blocks_note"] = "只统计每行非空数值单元格；空列被跳过，不一定是连续列或完整数据范围。"
    result["maximum_columns"] = max((len(row) for row in rows), default=0)
    return result
