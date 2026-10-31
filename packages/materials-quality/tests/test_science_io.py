"""Real files and local services exercise source preservation and parsing."""

import json
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pandas as pd
import pytest
from PIL import Image


def test_csv_encoding_delimiter_header_and_range(tmp_path):
    from materials_quality.science.io_nodes import table_import

    source = tmp_path / "measurements.csv"
    source.write_bytes("说明;;\n样品;温度;多余\n甲;20;0\n乙;30;1\n".encode("gb18030"))
    original = source.read_bytes()
    result = table_import(config={"path": str(source), "header": 1, "range": "A1:B4"})
    assert result.table.to_dict("list") == {"样品": ["甲", "乙"], "温度": [20, 30]}
    assert result.data["delimiter"] == ";"
    assert result.data["encoding"] == "gb18030"
    assert source.read_bytes() == original


def test_excel_sheet_header_range(tmp_path):
    from materials_quality.science.io_nodes import table_import

    source = tmp_path / "sheets.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame([["note", None, None], ["id", "value", "drop"], ["S1", 12, 99]]).to_excel(
            writer, sheet_name="Experiment", index=False, header=False
        )
    result = table_import(config={"path": str(source), "sheet": "Experiment", "header": 0, "range": "A2:B3"})
    assert result.table.to_dict("records") == [{"id": "S1", "value": 12}]
    assert result.data["sheet"] == "Experiment"


@pytest.mark.parametrize(
    "method,text,config,expected",
    [
        ("lines", "alpha\nbeta\n", {}, {"line_number": [1, 2], "text": ["alpha", "beta"]}),
        ("delimited", "x|y\n1|2\n", {"delimiter": "|"}, {"x": [1], "y": [2]}),
        (
            "fixed_width",
            "AB0012\nCD0034\n",
            {"widths": [2, 4], "names": ["sample", "value"]},
            {"sample": ["AB", "CD"], "value": [12, 34]},
        ),
    ],
)
def test_text_parsers(tmp_path, method, text, config, expected):
    from materials_quality.science.io_nodes import text_import

    source = tmp_path / "data.txt"
    source.write_text(text, encoding="utf-8")
    result = text_import(config={"path": str(source), "method": method, **config})
    assert result.table.to_dict("list") == expected


def test_image_metadata_and_upstream_path(tmp_path):
    from materials_quality.science.io_nodes import image_import

    source = tmp_path / "image.png"
    Image.new("RGB", (80, 40), "white").save(source, dpi=(150, 150))
    result = image_import(data={"file_path": str(source)})
    assert result.data["width"] == 80 and result.data["height"] == 40
    assert result.data["format"] == "PNG"
    assert result.data["dpi"][0] == pytest.approx(150, abs=0.1)


@pytest.mark.parametrize(
    "suffix,content,expected",
    [
        ("xy", "# synthetic spectrum\n10 100\n20 200\n", [[10.0, 100.0], [20.0, 200.0]]),
        ("jdx", "##TITLE=synthetic\n##XYDATA=(XY..XY)\n1,4\n2,8\n##END=\n", [[1.0, 4.0], [2.0, 8.0]]),
        (
            "dx",
            "##TITLE=synthetic\n##FIRSTX=10\n##LASTX=12\n##NPOINTS=3\n##XFACTOR=1\n"
            "##YFACTOR=2\n##XYDATA=(X++(Y..Y))\n10 2 3 4\n##END=\n",
            [[10.0, 4.0], [11.0, 6.0], [12.0, 8.0]],
        ),
    ],
)
def test_instrument_xy_and_jcamp(tmp_path, suffix, content, expected):
    from materials_quality.science.io_nodes import instrument_import

    source = tmp_path / f"sample.{suffix}"
    source.write_text(content, encoding="utf-8")
    result = instrument_import(config={"path": str(source)})
    assert result.table[["x", "y"]].values.tolist() == expected


def test_brml_xml_raw_points(tmp_path):
    import zipfile

    from materials_quality.science.io_nodes import instrument_import

    source = tmp_path / "scan.brml"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "Experiment0/RawData0.xml",
            "<RawData><DataRoutes><DataRoute>"
            "<Datum>0,1,100,10,50</Datum><Datum>1,1,100,20,75</Datum>"
            "</DataRoute></DataRoutes></RawData>",
        )
    result = instrument_import(config={"path": str(source), "x_index": 3, "y_index": 4})
    assert result.table[["x", "y"]].values.tolist() == [[10.0, 50.0], [20.0, 75.0]]
    assert result.data["xml_members"] == ["Experiment0/RawData0.xml"]


def test_unsupported_binary_requires_plugin_and_executes_explicit_converter(tmp_path, monkeypatch):
    from materials_quality.science.io_nodes import instrument_import

    source = tmp_path / "sample.raw"
    source.write_bytes(b"vendor binary")
    with pytest.raises(ValueError, match="converter|plugin"):
        instrument_import(config={"path": str(source)})
    plugin = tmp_path / "test_io_plugin.py"
    plugin.write_text(
        "import pandas as pd\ndef convert(path, config):\n"
        "    assert path.read_bytes() == b'vendor binary'\n"
        "    return pd.DataFrame({'x':[1.], 'y':[7.]})\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    result = instrument_import(config={"path": str(source), "plugin": "test_io_plugin:convert"})
    assert result.table.to_dict("list") == {"x": [1.0], "y": [7.0]}
    assert source.read_bytes() == b"vendor binary"
    sys.modules.pop("test_io_plugin", None)


@pytest.mark.parametrize("method", ["sqlite", "sqlalchemy"])
def test_database_readonly_query_field_selection(tmp_path, method):
    from materials_quality.science.io_nodes import database_import

    source = tmp_path / "measure.db"
    with sqlite3.connect(source) as connection:
        connection.execute("create table samples (id text, value real)")
        connection.executemany("insert into samples values (?,?)", [("S1", 2.0), ("S2", 4.0)])
    config = {
        "method": method,
        "path": str(source),
        "query": "select * from samples where value > :v",
        "parameters": {"v": 2},
        "fields": ["id"],
    }
    if method == "sqlalchemy":
        config["url"] = "sqlite:///" + source.as_posix()
    result = database_import(config=config)
    assert result.table.to_dict("list") == {"id": ["S2"]}
    with pytest.raises(ValueError, match="read.only|SELECT|select"):
        database_import(config={**config, "query": "delete from samples"})
    with sqlite3.connect(source) as connection:
        assert connection.execute("select count(*) from samples").fetchone()[0] == 2


def test_rest_pagination_and_nested_field_selection():
    from materials_quality.science.io_nodes import database_import

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            from urllib.parse import parse_qs, urlparse

            page = int(parse_qs(urlparse(self.path).query).get("page", ["1"])[0])
            payload = {"items": [{"id": page, "result": {"value": page * 3}}]} if page < 3 else {"items": []}
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        result = database_import(
            config={
                "method": "rest",
                "url": f"http://127.0.0.1:{server.server_port}/",
                "records_path": "items",
                "fields": ["id", "result.value"],
                "pagination": {"mode": "page", "page_size": 1},
            }
        )
        assert result.table.to_dict("list") == {"id": [1, 2], "result.value": [3, 6]}
        assert result.data["pages_read"] == 3
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_pdf_import_native_and_scanned_page_artifact(tmp_path):
    import fitz

    from materials_quality.science.io_nodes import pdf_import

    source = tmp_path / "mixed.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((40, 50), "Native experiment")
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (200, 100), "white").save(image_path)
    doc.new_page().insert_image(fitz.Rect(0, 0, 200, 100), filename=str(image_path))
    doc.save(source)
    doc.close()
    result = pdf_import(config={"path": str(source), "output_dir": str(tmp_path / "out")})
    assert "Native experiment" in result.data["pages"][0]["text"]
    assert result.data["pages"][0]["blocks"][0]["bbox"][0] > 0
    assert result.data["pages"][1]["requires_ocr"] is True
    with Image.open(result.artifacts[0]) as image:
        assert image.width > 200


def test_invalid_parser_configuration_rejected(tmp_path):
    from materials_quality.science.io_nodes import text_import

    source = tmp_path / "input.txt"
    source.write_text("abc", encoding="utf-8")
    with pytest.raises(ValueError, match="width"):
        text_import(config={"path": str(source), "method": "fixed_width", "widths": [0]})


def test_converter_command_receives_isolated_input_and_real_output(tmp_path):
    from materials_quality.science.io_nodes import instrument_import

    source = tmp_path / "vendor input.raw"
    source.write_bytes(b"raw experiment")
    converter = tmp_path / "converter.py"
    converter.write_text(
        "import pathlib,sys\n"
        "pathlib.Path(sys.argv[1]).write_bytes(b'modified by converter')\n"
        "pathlib.Path(sys.argv[2]).write_text('x,y\\n2,9\\n',encoding='utf-8')\n",
        encoding="utf-8",
    )
    result = instrument_import(
        config={
            "path": str(source),
            "output_dir": str(tmp_path / "converted"),
            "converter": [sys.executable, str(converter), "{input}", "{output}"],
        }
    )
    assert result.table.to_dict("list") == {"x": [2], "y": [9]}
    assert source.read_bytes() == b"raw experiment"
    assert pd.read_csv(result.artifacts[0]).to_dict("list") == {"x": [2], "y": [9]}


def test_plugin_receives_isolated_input(tmp_path, monkeypatch):
    from materials_quality.science.io_nodes import instrument_import

    source = tmp_path / "sample.raw"
    source.write_bytes(b"original")
    plugin = tmp_path / "mutable_io_plugin.py"
    plugin.write_text(
        "import pandas as pd\ndef convert(path, config):\n"
        "    path.write_bytes(b'changed')\n"
        "    return pd.DataFrame({'x':[1], 'y':[2]})\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    instrument_import(config={"path": str(source), "plugin": "mutable_io_plugin:convert"})
    assert source.read_bytes() == b"original"
    sys.modules.pop("mutable_io_plugin", None)


@pytest.mark.parametrize("mode", ["offset", "next", "none"])
def test_rest_alternative_pagination_modes(mode):
    from urllib.parse import parse_qs, urlparse

    from materials_quality.science.io_nodes import database_import

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            params = parse_qs(urlparse(self.path).query)
            index = int(params.get("offset", params.get("cursor", ["0"]))[0])
            payload = {
                "rows": [{"value": index + 10}] if index < 2 else [],
                "next": f"/?cursor={index + 1}" if index < 1 else None,
            }
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        result = database_import(
            config={
                "method": "rest",
                "url": f"http://127.0.0.1:{server.server_port}/",
                "records_path": "rows",
                "pagination": {"mode": mode, "page_size": 1},
            }
        )
        assert result.table["value"].tolist() == ([10] if mode == "none" else [10, 11])
        assert result.data["complete"] is True
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_rest_max_pages_reports_incomplete():
    from materials_quality.science.io_nodes import database_import

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'[{"x": 1}]')

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        result = database_import(
            config={
                "method": "rest",
                "url": f"http://127.0.0.1:{server.server_port}/",
                "pagination": {"max_pages": 1},
            }
        )
        assert result.data["complete"] is False
        assert "incomplete" in result.warnings[0]
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.mark.parametrize("route", ["redirect", "next"])
def test_rest_rejects_cross_origin_before_authorization_is_sent(route):
    from materials_quality.science.io_nodes import database_import

    received = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, *_args):
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    target_url = f"http://127.0.0.1:{target.server_port}/"

    class Source(BaseHTTPRequestHandler):
        def do_GET(self):
            if route == "redirect":
                self.send_response(302)
                self.send_header("Location", target_url)
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"items": [{"x": 1}], "next": target_url}).encode())

        def log_message(self, *_args):
            pass

    source = ThreadingHTTPServer(("127.0.0.1", 0), Source)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (source, target)]
    for thread in threads:
        thread.start()
    try:
        with pytest.raises(ValueError, match="origin"):
            database_import(
                config={
                    "method": "rest",
                    "url": f"http://127.0.0.1:{source.server_port}/",
                    "headers": {"Authorization": "Bearer review-secret"},
                    "records_path": "items" if route == "next" else "",
                    "pagination": {"mode": "next" if route == "next" else "none"},
                }
            )
        assert received == [], "Cross-origin target must receive no request or Authorization header"
    finally:
        for server in (source, target):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join()


def test_converter_cannot_claim_stale_output_when_process_writes_nothing(tmp_path):
    from materials_quality.science.io_nodes import instrument_import

    source = tmp_path / "new.raw"
    source.write_bytes(b"new raw measurement")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    stale = output_dir / "instrument-converted.csv"
    stale.write_text("x,y\n99,123\n", encoding="utf-8")
    with pytest.raises(ValueError, match="output|create|produce"):
        instrument_import(
            config={
                "path": str(source),
                "output_dir": str(output_dir),
                "overwrite": True,
                "converter": [sys.executable, "-c", "pass", "{input}", "{output}"],
            }
        )
    assert stale.read_text(encoding="utf-8") == "x,y\n99,123\n"
    assert source.read_bytes() == b"new raw measurement"


def test_import_preserves_leading_zero_ids_and_explicit_text_schema(tmp_path):
    from materials_quality.science.io_nodes import table_import

    source = tmp_path / "identifiers.csv"
    source.write_text("sample_id,batch,value\n001,NA,1\n01,7,2\n1,8,3\n", encoding="utf-8")
    result = table_import(
        config={"path": str(source), "id_columns": ["sample_id"], "dtype": {"batch": "string"}}
    )
    assert result.table["sample_id"].tolist() == ["001", "01", "1"]
    assert result.table["batch"].tolist() == ["NA", "7", "8"]
    assert result.table["value"].tolist() == [1, 2, 3]
    inferred = table_import(config={"path": str(source)})
    assert inferred.table["sample_id"].tolist() == ["001", "01", "1"]


def test_excel_import_preserves_literal_na_and_text_identity(tmp_path):
    from materials_quality.science.io_nodes import table_import

    path = tmp_path / "identifiers.xlsx"
    pd.DataFrame({"sample_id": ["NA", "001", "01"], "value": [1, 2, 3]}).to_excel(path, index=False)
    result = table_import(config={"path": str(path), "id_columns": ["sample_id"]})
    assert result.table["sample_id"].tolist() == ["NA", "001", "01"]
