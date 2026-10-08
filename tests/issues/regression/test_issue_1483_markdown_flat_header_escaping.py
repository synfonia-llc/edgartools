"""Flat Document Markdown headers must preserve literal pipes and backslashes.

GitHub Issue: https://github.com/dgunning/edgartools/issues/1483

The reported synthetic two-column header was emitted as three apparent cells.
A separate backslash-before-underscore example lost its literal backslash when
the Markdown was rendered. These tests use the public HTML parser and document
renderer, then decode the result with markdown-it-py's table rule.
"""

from html import escape

import pytest
from lxml import html as lxml_html
from markdown_it import MarkdownIt

from edgar.documents import Document, HTMLParser, ParserConfig
from edgar.documents.renderers.markdown import MarkdownRenderer
from edgar.documents.table_nodes import TableNode
from edgar.richtools import rich_to_text

pytestmark = pytest.mark.fast


def parse_document(header: str) -> Document:
    source = (
        "<html><body><table><thead><tr><th>Metric</th>"
        f"<th>{escape(header)}</th></tr></thead>"
        "<tbody><tr><td>Revenue</td><td>10</td></tr></tbody>"
        "</table></body></html>"
    )
    return HTMLParser(ParserConfig()).parse(source)


def first_table(document: Document) -> TableNode:
    tables = document.tables
    assert tables is not None
    assert len(tables) == 1
    table = tables[0]
    assert table is not None
    return table


def markdown_table(markdown: str) -> tuple[list[str], list[list[str]]]:
    rendered = MarkdownIt("commonmark").enable("table").render(markdown)
    tables = lxml_html.fromstring(rendered).xpath("//table")
    assert len(tables) == 1, rendered
    table = tables[0]
    headers = [cell.text_content() for cell in table.xpath("./thead/tr/th")]
    rows = [[cell.text_content() for cell in row.xpath("./td")] for row in table.xpath("./tbody/tr")]
    return headers, rows


@pytest.mark.parametrize(
    ("header", "escaped_header"),
    [
        pytest.param("Revenue | margin", r"Revenue \| margin", id="pipe"),
        pytest.param(r"Revenue\_forecast", r"Revenue\\_forecast", id="punctuation-backslash"),
        pytest.param(r"Revenue | margin\_forecast", r"Revenue \| margin\\_forecast", id="reported-pipe-and-backslash"),
        pytest.param(r"Revenue\|margin", r"Revenue\\\|margin", id="backslash-before-pipe"),
        pytest.param(r"Revenue\\|margin", r"Revenue\\\\\|margin", id="two-backslashes-before-pipe"),
        pytest.param("Revenue\\", r"Revenue\\", id="trailing-backslash"),
        pytest.param(r"Revenue\forecast", r"Revenue\\forecast", id="ordinary-backslash"),
        pytest.param("Revenue margin", "Revenue margin", id="plain-control"),
    ],
)
def test_flat_headers_preserve_literal_pipes_and_backslashes(header: str, escaped_header: str):
    document = parse_document(header)
    table = first_table(document)
    original = table.to_dict()
    spans = [[(cell.colspan, cell.rowspan) for cell in row] for row in table.headers]
    assert original["headers"] == [["Metric", header]]
    assert original["data"] == [["Revenue", "10"]]

    expected = f"| Metric | {escaped_header} |\n| --- | --- |\n| Revenue | 10 |"
    markdown = document.to_markdown()
    assert markdown == expected
    assert markdown_table(markdown) == (["Metric", header], [["Revenue", "10"]])
    assert document.to_markdown() == expected
    assert table.to_dict() == original
    assert [[(cell.colspan, cell.rowspan) for cell in row] for row in table.headers] == spans


def test_flat_header_newlines_are_normalized_before_escaping():
    document = parse_document("Revenue")
    table = first_table(document)
    # A controlled public Cell isolates the renderer from parser whitespace rules.
    table.headers[0][1].content = "Revenue |\nmargin\\_forecast"
    original = table.to_dict()

    markdown = document.to_markdown()
    assert markdown == "| Metric | Revenue \\| margin\\\\_forecast |\n| --- | --- |\n| Revenue | 10 |"
    assert markdown_table(markdown) == (["Metric", r"Revenue | margin\_forecast"], [["Revenue", "10"]])
    assert table.to_dict() == original


@pytest.mark.parametrize("width", [40, 200])
def test_rich_before_markdown_keeps_flat_literal_headers(width: int):
    document = parse_document(r"Revenue | margin\_forecast")
    table = first_table(document)
    rich_to_text(table.render(width=width), width=width)
    original = table.to_dict()

    markdown = document.to_markdown()
    assert markdown_table(markdown) == (["Metric", r"Revenue | margin\_forecast"], [["Revenue", "10"]])
    assert document.to_markdown() == markdown
    assert table.to_dict() == original


@pytest.mark.parametrize("table_format", ["grid", "simple"])
def test_other_table_formats_keep_literal_header_text(table_format: str):
    header = r"Revenue | margin\_forecast"
    document = parse_document(header)
    table = first_table(document)
    original = table.to_dict()

    rendered = MarkdownRenderer(table_format=table_format).render(document)
    assert header in rendered
    assert table.to_dict() == original
