"""Bounded structural inspection of a research file named by the user."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import re
import zipfile
from pathlib import Path

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_EXPANDED_BYTES = 150 * 1024 * 1024
SUPPORTED = {".csv", ".tsv", ".txt", ".ras", ".lis", ".xlsx", ".xlsm"}
NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
LIS_NUMBER = re.compile(r"^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?$")
READ_DENIAL = re.compile(
    r"(?:不要|禁止|不得|不许|切勿|撤销).{0,12}(?:读取|访问|打开|检查|分析文件|文件访问)"
    r"|(?:不允许|禁止).{0,8}文件(?:读取|访问)",
    re.I,
)


def authorized_file(path, user_text):
    """Only inspect a specific file explicitly supplied in this turn or session."""
    if not isinstance(path, str) or not path.strip() or len(path) > 1200:
        raise ValueError("请提供用户本轮明确指定的完整文件路径。")
    if READ_DENIAL.search(str(user_text)):
        raise PermissionError("用户已限制本次文件读取。")
    clean_path = path.strip().strip("'\"").replace("\\", "/")
    supplied = Path(clean_path)
    cwd = Path.cwd()
    original = cwd / supplied

    message = str(user_text).replace("\\", "/")
    quoted = re.compile(r"""(?<!\w)(?P<quote>["'`])(?P<path>[^\r\n]+?)(?P=quote)(?!\w)""")
    mentions = {match["path"] for match in quoted.finditer(message)}
    # Spaces are legal in paths. Unquoted paths occupy the whole line after
    # an optional read instruction, so a suffix of a longer path cannot match.
    prefix = re.compile(
        r"^(?:请帮我|请|帮我|please\s+)?\s*"
        r"(?:读取|访问|打开|检查|分析|研究|inspect|read|analy[sz]e|open|check)(?:\s+|[：:]\s*)",
        re.IGNORECASE,
    )
    for line in quoted.sub("\x00", message).splitlines():
        path_text = line.strip()
        if path_text.endswith((".", "。", "!", "！", "?", "？")):
            path_text = path_text[:-1].rstrip()
        mentions.add(prefix.sub("", path_text, count=1))
    candidates = {clean_path, original.as_posix()}
    resolved = original.resolve()
    for actual_path in (original, resolved):
        candidates.add(actual_path.as_posix())
        if actual_path.is_relative_to(cwd):
            relative = actual_path.relative_to(cwd).as_posix()
            candidates.update((relative, "./" + relative))

    matched = bool(candidates & mentions)
    if not matched and os.name == "nt":
        lowercase_paths = {candidate.lower() for candidate in candidates}
        for mention in mentions:
            if mention.lower() in lowercase_paths:
                mentioned_path = (cwd / mention).resolve()
                if mentioned_path.as_posix() == resolved.as_posix():
                    matched = True
                    break
    if not matched:
        raise PermissionError("只能检查用户在会话中明确提供或提及的数据文件路径。")
    if original.is_symlink():
        raise ValueError("不支持符号链接文件；请提供真实文件路径。")
    if not resolved.is_file() or resolved.suffix.casefold() not in SUPPORTED:
        raise ValueError("仅支持本地 CSV、TSV、TXT、RAS、LIS 和 Excel 数据文件。")
    if resolved.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("文件超过结构检查的 25 MB 上限。")
    return resolved


def _labels(row, row_number):
    # A mixed row may be a measurement row with sample identifiers; never
    # forward its text values as supposedly descriptive headers.
    if any(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        or isinstance(value, str)
        and bool(NUMBER.fullmatch(value.strip()))
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


def _lis_cells(line):
    cells = [cell.strip() for cell in line.split("\t")]
    while cells and not cells[-1]:
        cells.pop()
    return cells


def _lis_numeric_row(cells):
    values = [cell for cell in cells if cell]
    if len(values) < 2 or any(not LIS_NUMBER.fullmatch(value) for value in values):
        return None
    try:
        numbers = [float(value.replace(",", ".")) for value in values]
    except (ValueError, OverflowError):
        return None
    return numbers if all(math.isfinite(value) for value in numbers) else None


def _inspect_lis(path, raw, result):
    """Inspect BAM LIS section/table metadata without returning measurement rows."""
    try:
        text = raw.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
            encoding = "cp1252"
        except UnicodeDecodeError:
            text = raw.decode("latin1")
            encoding = "latin1"

    lines = text.splitlines()
    section_rows = []
    table_sections = []
    labels = []
    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if re.fullmatch(r"\[[^\]]{1,80}\]", stripped):
            section_rows.append({"line": line_number, "name": stripped[1:-1]})
            marker_index = line_number
            header_index = marker_index
            while header_index < len(lines) and not lines[header_index].strip():
                header_index += 1
            if header_index >= len(lines) or re.fullmatch(r"[-=]{3,}", lines[header_index].strip()):
                continue

            header = _lis_cells(lines[header_index])
            if len([cell for cell in header if cell]) < 2 or _lis_numeric_row(header):
                continue
            units_index = header_index + 1
            while units_index < len(lines) and not lines[units_index].strip():
                units_index += 1
            if units_index >= len(lines):
                units = []
                data_index = units_index
            else:
                units_candidate = _lis_cells(lines[units_index])
                # A unit row is metadata, not a data row. Keep only the
                # intersection so inconsistent widths are visible, not guessed.
                units = units_candidate if not _lis_numeric_row(units_candidate) else []
                data_index = units_index + 1 if units else units_index

            data_rows = 0
            first_data_line = None
            last_data_line = None
            first_column_values = []
            for row_index in range(data_index, len(lines)):
                row = _lis_cells(lines[row_index])
                if not row:
                    if data_rows:
                        break
                    continue
                numbers = _lis_numeric_row(row)
                if numbers is None:
                    break
                data_rows += 1
                first_data_line = first_data_line or row_index + 1
                last_data_line = row_index + 1
                first_column_values.append(numbers[0])

            first_column_order = None
            if len(first_column_values) >= 2:
                differences = [
                    right - left
                    for left, right in zip(first_column_values, first_column_values[1:], strict=False)
                ]
                first_column_order = {
                    "checked_rows": len(first_column_values),
                    "strictly_increasing": all(value > 0 for value in differences),
                    "strictly_decreasing": all(value < 0 for value in differences),
                    "adjacent_equal_count": sum(value == 0 for value in differences),
                }
            table = {
                "section": stripped[1:-1],
                "header_line": header_index + 1,
                "data_start_line": first_data_line,
                "data_end_line": last_data_line,
                "data_rows": data_rows,
                "columns": len(header),
                "headers": header[:80],
                "units": units[:80],
                "first_column_order": first_column_order,
            }
            table_sections.append(table)
            if not labels:
                labels = [
                    {"row": header_index + 1, "column": index, "label": value}
                    for index, value in enumerate(header, 1)
                    if value
                ][:100]

    result.update(
        encoding=encoding,
        delimiter="\t",
        rows=len(lines),
        maximum_columns=max((len(_lis_cells(line)) for line in lines), default=0),
        sections=section_rows[:80],
        table_sections=table_sections[:40],
        first_row_text_labels=labels,
        numeric_blocks=[
            {
                "section": table["section"],
                "start_row": table["data_start_line"],
                "end_row": table["data_end_line"],
                "data_rows": table["data_rows"],
                "nonempty_numeric_cells_per_row": table["columns"],
                "first_column_order": table["first_column_order"],
                "first_column_order_note": "仅检查该表第一列的顺序；物理含义由表头和单位标识。",
            }
            for table in table_sections
            if table["data_rows"]
        ][:20],
        numeric_blocks_note="仅返回各节连续数值行的结构统计，不包含任何测量值。",
        recommended_import_config={
            "encoding": encoding,
            "delimiter": "\t",
            "note": "BAM LIS 含多个命名区段和逗号小数；请选定已核验区段并处理小数格式后再做数值分析。",
        },
        note=(
            "BAM LIS 结构检查仅返回区段、列标签、单位、行数和顺序标志；"
            "不返回测量行或具体数值。逗号小数及不同区段须在导入/分析分支单独核验。"
        ),
    )
    labels_text = [cell["label"] for cell in labels]
    result["standards_and_compliance"] = audit_standards_and_dimensions(path, labels_text, None)
    return result


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
                for row_number, row in enumerate(
                    sheet.iter_rows(
                        min_row=1,
                        max_row=max(observed_rows, 1),
                        max_col=min(sheet.max_column or 1, 512),
                        values_only=True,
                    ),
                    1,
                ):
                    if row_number <= 2:
                        row_labels = _labels(row, row_number)
                        labels.extend(row_labels[:35])
                        header_map.update({item["column"]: item["label"] for item in row_labels})
                    used_columns.update(
                        index for index, value in enumerate(row, 1) if value is not None and value != ""
                    )
                    for column, value in enumerate(row, 1):
                        number = isinstance(value, (int, float)) and not isinstance(value, bool)
                        numeric_text = isinstance(value, str) and bool(NUMBER.fullmatch(value.strip()))
                        if (number or numeric_text) and math.isfinite(float(value)):
                            numeric_positions.setdefault(column, set()).add(row_number)
                    if row_number >= 3:
                        for column, value in enumerate(row, 1):
                            if (
                                isinstance(value, str)
                                and value.strip()
                                and not NUMBER.fullmatch(value.strip())
                            ):
                                text_positions.setdefault(column, []).append(row_number)
                            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                                numeric_columns.add(column)
                sparse = []
                for column, positions in text_positions.items():
                    if (
                        column in numeric_columns
                        or not 2 <= len(positions) <= 50
                        or len(positions) * 4 >= max(observed_rows - 2, 1)
                    ):
                        continue
                    gaps = [b - a for a, b in zip(positions, positions[1:], strict=False)]
                    sparse.append(
                        {
                            "column": column,
                            "nonempty_text_cells": len(positions),
                            "rows": positions,
                            "uniform_spacing": gaps[0] if gaps and len(set(gaps)) == 1 else None,
                        }
                    )
                pairs = []
                for column, positions in numeric_positions.items():
                    shared = positions & numeric_positions.get(column + 1, set())
                    if len(shared) < 2:
                        continue
                    first, last = min(shared), max(shared)
                    pairs.append(
                        {
                            "columns": [column, column + 1],
                            "candidate_headers": [header_map.get(column), header_map.get(column + 1)],
                            "paired_finite_rows": len(shared),
                            "first_row": first,
                            "last_row": last,
                            "contiguous": last - first + 1 == len(shared),
                        }
                    )
                pairs.sort(key=lambda pair: (-pair["paired_finite_rows"], pair["columns"][0]))
                result["sheets"].append(
                    {
                        "name": sheet.title,
                        "rows": sheet.max_row,
                        "columns": sheet.max_column,
                        "observed_rows_for_used_columns": observed_rows,
                        "observed_nonempty_columns": len(used_columns),
                        "observed_last_nonempty_column": max(used_columns, default=0),
                        "sparse_text_columns_after_first_two_rows": sparse[:20],
                        "adjacent_numeric_pairs": pairs[:8],
                        "pair_note": ("仅说明相邻列数值覆盖。列的物理含义需依据候选表头和来源核实。"),
                        "first_two_rows_text_labels": labels,
                        "labels_may_be_truncated": True,
                    }
                )
        finally:
            book.close()
        if result.get("sheets"):
            sheet0 = result["sheets"][0]
            result["recommended_import_config"] = {
                "sheet": sheet0["name"],
                "header": 0 if sheet0.get("first_two_rows_text_labels") else None,
                "note": (
                    f"首选工作表 '{sheet0['name']}'，共 {sheet0.get('rows', 0)} 行、"
                    f"{sheet0.get('columns', 0)} 列。"
                ),
            }
        result["standards_and_compliance"] = audit_standards_and_dimensions(
            path,
            [cell["label"] for sheet in result["sheets"] for cell in sheet["first_two_rows_text_labels"]],
            None,
        )
        return result

    if path.suffix.lower() == ".lis":
        return _inspect_lis(path, raw, result)

    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936", "shift_jis", "latin1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("无法识别文本编码，仅支持常见 UTF-8、GBK/GB18030 及 Shift-JIS 编码文本文件。")
    try:
        delimiter = (
            " "
            if path.suffix.lower() == ".ras"
            else csv.Sniffer().sniff(text[:65536], delimiters=",;\t| ").delimiter
        )
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
                blocks.append(
                    {"start_row": start, "end_row": index - 1, "nonempty_numeric_cells_per_row": width}
                )
            start, width = (index, len(values)) if numeric else (None, None)
    result["numeric_blocks"] = sorted(blocks, key=lambda b: b["end_row"] - b["start_row"], reverse=True)[:5]
    for block in result["numeric_blocks"]:
        selected = rows[block["start_row"] - 1 : block["end_row"]]
        values = []
        for row in selected:
            if not row or not NUMBER.fullmatch(row[0].strip()):
                values = []
                break
            value = float(row[0])
            if not math.isfinite(value):
                values = []
                break
            values.append(value)
        if len(values) >= 2:
            differences = [b - a for a, b in zip(values, values[1:], strict=False)]
            dec = all(d < 0 for d in differences)
            block["first_column_order"] = {
                "checked_rows": len(values),
                "strictly_increasing": all(d > 0 for d in differences),
                "strictly_decreasing": dec,
                "adjacent_equal_count": sum(d == 0 for d in differences),
            }
            if dec:
                block["first_column_order"]["warning"] = (
                    "第一列严格递减。如目标算法要求横轴递增，确认列含义后可对配对行按该列排序。"
                )
            block["first_column_order_note"] = "仅为该数值区块第一列的顺序检查，不确定其物理含义。"
    result["numeric_blocks_note"] = "只统计每行非空数值单元格；空列被跳过，不一定是连续列或完整数据范围。"
    result["maximum_columns"] = max((len(row) for row in rows), default=0)
    recommended = {
        "encoding": encoding,
        "delimiter": delimiter,
    }
    if result.get("numeric_blocks"):
        main_block = result["numeric_blocks"][0]
        if main_block["start_row"] > 2:
            recommended["header"] = None
            recommended["skip_rows"] = main_block["start_row"] - 1
            recommended["start_row"] = main_block["start_row"]
            recommended["end_row"] = main_block["end_row"]
            recommended["note"] = (
                f"第 {main_block['start_row']} 行起为主要连续数值区。可设置数据区间或跳过前置行。"
            )
        elif main_block["start_row"] == 2:
            recommended["header"] = 0
            recommended["note"] = "第 1 行为表头，第 2 行起为数值。"
        else:
            recommended["header"] = 0 if result.get("first_row_text_labels") else None
    result["recommended_import_config"] = recommended
    result["standards_and_compliance"] = audit_standards_and_dimensions(
        path,
        [lbl["label"] for lbl in result.get("first_row_text_labels", [])],
        main_block if result.get("numeric_blocks") else None,
    )
    return result


# Reference names are research hints. Applicability depends on the
# specimen, method, instrument and edition.
DOMAIN_HINTS = (
    (
        ("ti64", "tensile", "拉伸", "strain", "stress", "应力", "应变", "力学"),
        "金属力学性能测试",
        "ASTM E8 / GB/T 228.1",
        (
            ("units", "应力与应变单位"),
            ("yield_sampling", "0.2% 偏移屈服拟合点密度"),
            ("elongation", "原始标距及断后延伸率"),
        ),
    ),
    (
        ("xrd", "衍射", "zirconia", "2theta", "diffraction", "3ysz"),
        "X射线晶相结构分析",
        "ASTM E915",
        (("axis_units", "角度列及其物理单位"), ("peak_sampling", "物相检索步长与峰形拟合")),
    ),
    (
        ("spectra", "spectrum", "raman", "光谱", "wavelength"),
        "多通道光谱分析",
        "ASTM E1840",
        (("axis_units", "波长或波数列及其物理单位"), ("peak_threshold", "基线噪声与寻峰阈值")),
    ),
    (
        ("battery", "cycle", "soc", "充放电", "电池"),
        "电化学储能循环测试",
        "IEC 62660 / GB/T 31486",
        (("cycle_direction", "充放电方向"), ("voltage_window", "电压截止窗口")),
    ),
    (
        ("contrast", "组间", "显著性", "repeat", "重复"),
        "实验组间设计与统计推断",
        "ISO/TR 22971",
        (("replication", "独立试样和技术重复"), ("significance", "显著性水平与置信区间")),
    ),
)


def audit_standards_and_dimensions(path: Path, labels: list[str], main_block: dict | None) -> dict:
    """Report structural evidence and reference hints for further review.

    Check statuses are passed, failed, not_verified, or not_applicable. The
    first two describe the stated criterion within its scope. A format-level
    inspection leaves overall standards compliance undetermined.
    """
    filename = path.name.casefold()
    label_text = " ".join(labels).casefold()
    domain, standard, checks = "领域待确认", None, ()
    hint_evidence = {"filename_terms": [], "label_terms": []}
    for terms, candidate_domain, candidate_standard, candidate_checks in DOMAIN_HINTS:
        filename_terms = [term for term in terms if term in filename]
        label_terms = [term for term in terms if term in label_text]
        if filename_terms or label_terms:
            domain, standard, checks = candidate_domain, candidate_standard, candidate_checks
            hint_evidence = {"filename_terms": filename_terms, "label_terms": label_terms}
            break

    results = [
        {
            "id": key,
            "item": label,
            "status": "not_verified",
            "scope": "领域候选检查",
            "evidence": None,
            "detail": "需结合实验记录、列定义及适用的标准条款核实。",
        }
        for key, label in checks
    ]
    order = (main_block or {}).get("first_column_order")
    order_status = "not_verified"
    scope = {"column": 1}
    if main_block:
        scope.update(start_row=main_block.get("start_row"), end_row=main_block.get("end_row"))
    if (
        isinstance(order, dict)
        and isinstance(order.get("strictly_increasing"), bool)
        and isinstance(order.get("checked_rows"), int)
        and order["checked_rows"] >= 2
    ):
        order_status = "passed" if order["strictly_increasing"] else "failed"
    results.append(
        {
            "id": "first_column_increasing",
            "item": "主数值区第一列严格递增",
            "status": order_status,
            "scope": scope,
            "evidence": order,
            "detail": (
                "判据为区块中所有相邻有限数值严格递增。此项仅检查记录顺序，物理轴身份及标准适用性待核实。"
            ),
        }
    )
    return {
        "standard": standard,
        "standard_status": "reference_hint" if standard else "not_verified",
        "domain": domain,
        "domain_status": "suggested" if standard else "not_verified",
        "domain_evidence": hint_evidence,
        "checks": results,
        "compliance_status": "not_verified",
        "compliance_passed": None,
    }
