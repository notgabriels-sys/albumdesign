from PIL import Image
import pytest

from coverforge.contactsheet import ContactSheetError, plan_contact_sheet, write_contact_sheet
from coverforge.imageops import inspect


def test_contact_sheet_writes_a_deterministic_offline_review_packet(art_factory, tmp_path):
    sources = [
        inspect(art_factory("variant-one", size=(3000, 3000))),
        inspect(art_factory("variant-two", size=(2000, 3000))),
        inspect(art_factory("variant-three", size=(3000, 2000))),
    ]
    output = tmp_path.parent / f"{tmp_path.name}-review"

    result = write_contact_sheet(
        sources,
        output,
        title="Set Three",
        columns=2,
        cell_size=120,
    )

    assert sorted(path.name for path in output.iterdir()) == [
        "CONTACT_SHEET.html",
        "CONTACT_SHEET.jpg",
    ]
    assert result.source_count == 3
    assert result.dimensions == "324x492"
    with Image.open(output / "CONTACT_SHEET.jpg") as sheet:
        assert sheet.size == (324, 492)
        assert sheet.mode == "RGB"

    html = (output / "CONTACT_SHEET.html").read_text(encoding="utf-8")
    assert "Set Three" in html
    assert "CONTACT_SHEET.jpg" in html
    assert all(source.path.name in html for source in sources)
    assert str(tmp_path) not in html


def test_contact_sheet_refuses_output_inside_a_selected_image_directory(art_factory, tmp_path):
    source = inspect(art_factory("variant", size=(3000, 3000)))
    output = source.path.parent / "review"

    with pytest.raises(ContactSheetError, match="outside selected image directories"):
        write_contact_sheet([source], output)

    assert not output.exists()


def test_contact_sheet_plan_validates_layout_without_writing(art_factory, tmp_path):
    sources = [
        inspect(art_factory("variant-one", size=(3000, 3000))),
        inspect(art_factory("variant-two", size=(3000, 2000))),
    ]
    output = tmp_path.parent / f"{tmp_path.name}-review"

    result = plan_contact_sheet(sources, output, columns=2, cell_size=120)

    assert result.source_count == 2
    assert result.dimensions == "324x304"
    assert not output.exists()


def test_contact_sheet_keeps_output_absent_when_a_preview_cannot_be_composed(art_factory, tmp_path):
    source = inspect(art_factory("variant", size=(3000, 3000)))
    source.path.unlink()
    output = tmp_path.parent / f"{tmp_path.name}-review"

    with pytest.raises(ContactSheetError, match="could not compose contact-sheet preview"):
        write_contact_sheet([source], output)

    assert not output.exists()


def test_contact_sheet_escapes_hostile_variant_filenames_in_html(art_factory, tmp_path):
    harmless = art_factory("variant", size=(3000, 3000))
    hostile = harmless.with_name("<img src=x onerror=alert(1)>.png")
    harmless.rename(hostile)
    output = tmp_path.parent / f"{tmp_path.name}-review"

    write_contact_sheet([inspect(hostile)], output)

    html = (output / "CONTACT_SHEET.html").read_text(encoding="utf-8")
    assert hostile.name not in html
    assert "&lt;img src=x onerror=alert(1)&gt;.png" in html
