"""Headerless HTML tables need a blank Markdown header and delimiter.

GitHub Issue: https://github.com/dgunning/edgartools/issues/1484

The numeric two-row example is synthetic and must keep 10/20 and 30/40 in
body cells. The GSBD FY2025 10-K excerpt (0001193125-26-077458, table 10)
retains the filed fourth-quarter NAV of $12.64 per share. Its visual headers
are still classified as body rows, and its multiline cells remain a separate
reported limitation. Rendering must not change the parsed source table.
"""

from pathlib import Path

import pytest
from lxml import html as lxml_html
from markdown_it import MarkdownIt

from edgar.documents import Document, HTMLParser, ParserConfig
from edgar.documents.renderers.markdown import MarkdownRenderer
from edgar.documents.table_nodes import Cell, Row, TableNode
from edgar.richtools import rich_to_text

pytestmark = pytest.mark.fast

GSBD = Path(__file__).parents[2] / "fixtures" / "html" / "issue1484" / "gsbd-20251231-table-10-excerpt.html"
NUMERIC_ROWS = "<tr><td>10</td><td>20</td></tr><tr><td>30</td><td>40</td></tr>"
EXPECTED_NUMERIC_MARKDOWN = "|  |  |\n| --- | --- |\n| 10 | 20 |\n| 30 | 40 |"


def parse_document(source: str | bytes, form: str | None = None, fast_table_rendering: bool = True) -> Document:
    config = ParserConfig(form=form, enable_parallel=False, max_workers=1, fast_table_rendering=fast_table_rendering)
    return HTMLParser(config).parse(source)


def first_table(document: Document) -> TableNode:
    tables = document.tables
    assert tables is not None
    table = tables[0]
    assert table is not None
    return table


def markdown_table(markdown: str) -> tuple[list[str], list[list[str]]]:
    rendered = MarkdownIt("commonmark").enable("table").render(markdown)
    tables = lxml_html.fromstring(rendered).xpath("//table")
    assert len(tables) == 1
    table = tables[0]
    headers = [cell.text_content() for cell in table.xpath("./thead/tr/th")]
    rows = [[cell.text_content() for cell in row.xpath("./td")] for row in table.xpath("./tbody/tr")]
    return headers, rows


@pytest.mark.parametrize("api", ["document", "renderer-document", "renderer-node"])
def test_headerless_rows_remain_markdown_body_cells(api):
    document = parse_document(f"<html><body><table><tbody>{NUMERIC_ROWS}</tbody></table></body></html>")
    table = first_table(document)
    assert table.headers == []
    assert [row.text() for row in table.rows] == ["10 | 20", "30 | 40"]
    before = table.to_dict()

    if api == "document":
        markdown = document.to_markdown()
    elif api == "renderer-document":
        markdown = MarkdownRenderer().render(document)
    else:
        markdown = MarkdownRenderer().render_node(table)

    assert markdown == EXPECTED_NUMERIC_MARKDOWN
    assert markdown_table(markdown) == (["", ""], [["10", "20"], ["30", "40"]])
    assert table.to_dict() == before
    assert table.headers == []


@pytest.mark.parametrize(
    ("source", "headers", "rows"),
    [
        pytest.param(
            "<tr><td>10</td><td></td><td>20</td></tr><tr><td>30</td><td></td><td>40</td></tr>",
            ["", ""],
            [["10", "20"], ["30", "40"]],
            id="blank-spacing-column",
        ),
        pytest.param(
            "<tr><td>10</td></tr><tr><td>30</td><td>40</td></tr>",
            ["", ""],
            [["10", ""], ["30", "40"]],
            id="later-row-wider",
        ),
        pytest.param(
            '<tr><td colspan="2">10</td><td>20</td></tr><tr><td>30</td><td>40</td><td>50</td></tr>',
            ["", "", ""],
            [["10", "", "20"], ["30", "40", "50"]],
            id="body-colspan",
        ),
    ],
)
def test_blank_header_matches_existing_filtered_body_columns(source, headers, rows):
    document = parse_document(f"<html><body><table><tbody>{source}</tbody></table></body></html>")
    table = first_table(document)
    assert table.headers == []
    before = table.to_dict()

    assert markdown_table(document.to_markdown()) == (headers, rows)
    assert table.to_dict() == before
    assert table.headers == []


@pytest.mark.parametrize("rows", [[], [Row([Cell(""), Cell(" ")])]], ids=["no-rows", "blank-rows"])
def test_empty_headerless_table_does_not_gain_markdown_scaffolding(rows):
    assert MarkdownRenderer().render_node(TableNode(rows=rows)) == ""


def test_gsbd_delimiter_keeps_the_filed_nav_in_its_body_row():
    document = parse_document(GSBD.read_bytes(), form="10-K")
    table = first_table(document)
    assert table.headers == []
    before = table.to_dict()

    markdown = document.to_markdown()
    lines = markdown.splitlines()
    quarter_row = next(line for line in lines if line.startswith("| Fourth Quarter |"))
    assert quarter_row.startswith("| Fourth Quarter | $ | 12.64 | $ | 10.14 | $ | 9.28 |")
    assert quarter_row.endswith("| $ | 0.36 |")
    column_count = quarter_row.count("|") - 1
    assert lines[0] == "| " + " | ".join([""] * column_count) + " |"
    delimiter = "| " + " | ".join(["---"] * column_count) + " |"
    assert lines[1] == delimiter
    assert lines.count(delimiter) == 1
    assert table.to_dict() == before
    assert table.headers == []


@pytest.mark.parametrize("fast_table_rendering", [False, True], ids=["rich-text", "fast-text"])
def test_synthetic_markdown_header_does_not_change_other_table_exports(fast_table_rendering):
    document = parse_document(
        f"<html><body><table><tbody>{NUMERIC_ROWS}</tbody></table></body></html>",
        fast_table_rendering=fast_table_rendering,
    )
    table = first_table(document)
    grid_before = MarkdownRenderer(table_format="grid").render(document)
    simple_before = MarkdownRenderer(table_format="simple").render(document)
    html_before = table.html()
    dataframe_before = table.to_dataframe()
    plain_before = document.text()
    rich_before = rich_to_text(table.render(width=195), width=195)
    source_before = table.to_dict()

    assert document.to_markdown() == EXPECTED_NUMERIC_MARKDOWN

    assert MarkdownRenderer(table_format="grid").render(document) == grid_before
    assert MarkdownRenderer(table_format="simple").render(document) == simple_before
    assert table.html() == html_before
    assert table.to_dataframe().equals(dataframe_before)
    assert document.text() == plain_before
    assert rich_to_text(table.render(width=195), width=195) == rich_before
    assert table.to_dict() == source_before
    assert table.headers == []
