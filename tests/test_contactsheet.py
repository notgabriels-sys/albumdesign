import json

from PIL import Image

from coverforge.cli import main


def test_cli_contactsheet_builds_packet(tmp_path, art_factory, capsys):
    assets = tmp_path / "assets"
    assets.mkdir()
    for _ in range(4):
        path = art_factory()
        path.rename(assets / path.name)

    out = tmp_path / "packet"
    assert (
        main(
            [
                "contactsheet",
                str(assets),
                "-o",
                str(out),
                "--columns",
                "2",
                "--cell-size",
                "300",
                "--title",
                "Lack of Fate — Drift",
            ]
        )
        == 0
    )

    sheet = out / "CONTACT_SHEET.jpg"
    index = out / "CONTACT_SHEET.html"
    assert sheet.exists()
    assert index.exists()
    with Image.open(sheet) as im:
        assert im.width > 300 and im.height > 300

    body = index.read_text(encoding="utf-8")
    assert "Lack of Fate — Drift" in body
    assert "4 selected variant(s)" in body


def test_cli_contactsheet_json_payload(tmp_path, art_factory, capsys):
    assets = tmp_path / "assets"
    assets.mkdir()
    for _ in range(3):
        path = art_factory()
        path.rename(assets / path.name)

    out = tmp_path / "packet"
    assert main(["contactsheet", str(assets), "-o", str(out), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    contact = payload["contact_sheet"]
    assert contact["source_count"] == 3
    assert contact["columns"] == 4
    assert contact["cell_size"] == 480
    assert contact["contact_sheet"].endswith("CONTACT_SHEET.jpg")
    assert contact["html_index"].endswith("CONTACT_SHEET.html")


def test_cli_contactsheet_fails_when_output_inside_source(tmp_path, art_factory, capsys):
    assets = tmp_path / "assets"
    assets.mkdir()
    for _ in range(2):
        img = art_factory()
        img.rename(assets / img.name)

    out = assets / "packet"
    assert (
        main(
            [
                "contactsheet",
                str(assets),
                "-o",
                str(out),
            ]
        )
        == 2
    )
    assert "output directory must be outside selected image directories" in capsys.readouterr().err
