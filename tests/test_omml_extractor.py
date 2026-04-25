"""Tests for raganything.omml_extractor.

These tests build minimal in-memory DOCX archives and OMML XML fragments so
the converter can be exercised end-to-end without requiring a real Word
document on disk.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

import pytest

from raganything.omml_extractor import (
    enrich_content_list_with_docx_equations,
    extract_omml_equations,
    omml_to_latex,
)

NS_DECL = (
    'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
)


def _wrap_in_omath(inner: str) -> ET.Element:
    """Parse `<m:oMath>{inner}</m:oMath>` into an Element with namespaces."""
    xml = f"<m:oMath {NS_DECL}>{inner}</m:oMath>"
    return ET.fromstring(xml)


def _make_docx(equations_xml: str) -> bytes:
    """Build a minimal in-memory DOCX archive containing the given equations.

    `equations_xml` should be a sequence of <m:oMath> elements (already
    namespaced with the m: prefix). They are inserted inside a single
    <w:p>/<w:r> paragraph so the resulting XML is well-formed.
    """
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {NS_DECL}>"
        "<w:body>"
        "<w:p>"
        f"{equations_xml}"
        "</w:p>"
        "</w:body>"
        "</w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", document_xml)
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
    buf.seek(0)
    return buf.getvalue()


class TestOmmlToLatex:
    """Direct conversion of OMML XML fragments to LaTeX."""

    def test_simple_run(self):
        elem = _wrap_in_omath("<m:r><m:t>x</m:t></m:r>")
        assert omml_to_latex(elem) == "x"

    def test_fraction(self):
        elem = _wrap_in_omath(
            "<m:f>"
            "<m:num><m:r><m:t>a</m:t></m:r></m:num>"
            "<m:den><m:r><m:t>b</m:t></m:r></m:den>"
            "</m:f>"
        )
        assert omml_to_latex(elem) == r"\frac{a}{b}"

    def test_superscript(self):
        elem = _wrap_in_omath(
            "<m:sSup>"
            "<m:e><m:r><m:t>x</m:t></m:r></m:e>"
            "<m:sup><m:r><m:t>2</m:t></m:r></m:sup>"
            "</m:sSup>"
        )
        assert omml_to_latex(elem) == "{x}^{2}"

    def test_subscript(self):
        elem = _wrap_in_omath(
            "<m:sSub>"
            "<m:e><m:r><m:t>x</m:t></m:r></m:e>"
            "<m:sub><m:r><m:t>i</m:t></m:r></m:sub>"
            "</m:sSub>"
        )
        assert omml_to_latex(elem) == "{x}_{i}"

    def test_sub_superscript(self):
        elem = _wrap_in_omath(
            "<m:sSubSup>"
            "<m:e><m:r><m:t>x</m:t></m:r></m:e>"
            "<m:sub><m:r><m:t>i</m:t></m:r></m:sub>"
            "<m:sup><m:r><m:t>2</m:t></m:r></m:sup>"
            "</m:sSubSup>"
        )
        assert omml_to_latex(elem) == "{x}_{i}^{2}"

    def test_radical_simple(self):
        elem = _wrap_in_omath(
            "<m:rad><m:deg></m:deg><m:e><m:r><m:t>x</m:t></m:r></m:e></m:rad>"
        )
        assert omml_to_latex(elem) == r"\sqrt{x}"

    def test_radical_with_degree(self):
        elem = _wrap_in_omath(
            "<m:rad>"
            "<m:deg><m:r><m:t>3</m:t></m:r></m:deg>"
            "<m:e><m:r><m:t>x</m:t></m:r></m:e>"
            "</m:rad>"
        )
        assert omml_to_latex(elem) == r"\sqrt[3]{x}"

    def test_summation_with_bounds(self):
        # ∑ from i=1 to n of x_i^2
        elem = _wrap_in_omath(
            "<m:nary>"
            '<m:naryPr><m:chr m:val="\u2211"/></m:naryPr>'
            "<m:sub><m:r><m:t>i=1</m:t></m:r></m:sub>"
            "<m:sup><m:r><m:t>n</m:t></m:r></m:sup>"
            "<m:e>"
            "<m:sSubSup>"
            "<m:e><m:r><m:t>x</m:t></m:r></m:e>"
            "<m:sub><m:r><m:t>i</m:t></m:r></m:sub>"
            "<m:sup><m:r><m:t>2</m:t></m:r></m:sup>"
            "</m:sSubSup>"
            "</m:e>"
            "</m:nary>"
        )
        assert omml_to_latex(elem) == r"\sum_{i=1}^{n} {x}_{i}^{2}"

    def test_integral_default_operator(self):
        # No m:chr → defaults to integral sign.
        elem = _wrap_in_omath(
            "<m:nary>"
            "<m:sub><m:r><m:t>0</m:t></m:r></m:sub>"
            "<m:sup><m:r><m:t>1</m:t></m:r></m:sup>"
            "<m:e><m:r><m:t>f</m:t></m:r></m:e>"
            "</m:nary>"
        )
        assert omml_to_latex(elem) == r"\int_{0}^{1} f"

    def test_known_function(self):
        elem = _wrap_in_omath(
            "<m:func>"
            "<m:fName><m:r><m:t>sin</m:t></m:r></m:fName>"
            "<m:e><m:r><m:t>x</m:t></m:r></m:e>"
            "</m:func>"
        )
        assert omml_to_latex(elem) == r"\sin{x}"

    def test_unknown_function_uses_parens(self):
        elem = _wrap_in_omath(
            "<m:func>"
            "<m:fName><m:r><m:t>foo</m:t></m:r></m:fName>"
            "<m:e><m:r><m:t>x</m:t></m:r></m:e>"
            "</m:func>"
        )
        assert omml_to_latex(elem) == "foo(x)"

    def test_delimiter_default_parentheses(self):
        elem = _wrap_in_omath("<m:d><m:e><m:r><m:t>x+y</m:t></m:r></m:e></m:d>")
        assert omml_to_latex(elem) == "(x+y)"

    def test_delimiter_brackets(self):
        elem = _wrap_in_omath(
            "<m:d>"
            '<m:dPr><m:begChr m:val="["/><m:endChr m:val="]"/></m:dPr>'
            "<m:e><m:r><m:t>x</m:t></m:r></m:e>"
            "</m:d>"
        )
        assert omml_to_latex(elem) == "[x]"

    def test_matrix_2x2(self):
        elem = _wrap_in_omath(
            "<m:m>"
            "<m:mr>"
            "<m:e><m:r><m:t>a</m:t></m:r></m:e>"
            "<m:e><m:r><m:t>b</m:t></m:r></m:e>"
            "</m:mr>"
            "<m:mr>"
            "<m:e><m:r><m:t>c</m:t></m:r></m:e>"
            "<m:e><m:r><m:t>d</m:t></m:r></m:e>"
            "</m:mr>"
            "</m:m>"
        )
        assert omml_to_latex(elem) == r"\begin{matrix} a & b \\ c & d \end{matrix}"

    def test_overline_via_bar(self):
        elem = _wrap_in_omath(
            "<m:bar>"
            '<m:barPr><m:pos m:val="top"/></m:barPr>'
            "<m:e><m:r><m:t>x</m:t></m:r></m:e>"
            "</m:bar>"
        )
        assert omml_to_latex(elem) == r"\overline{x}"

    def test_underline_via_bar(self):
        elem = _wrap_in_omath(
            "<m:bar>"
            '<m:barPr><m:pos m:val="bot"/></m:barPr>'
            "<m:e><m:r><m:t>x</m:t></m:r></m:e>"
            "</m:bar>"
        )
        assert omml_to_latex(elem) == r"\underline{x}"

    def test_unicode_symbol_substitution(self):
        # ≤ should map to \leq.
        elem = _wrap_in_omath("<m:r><m:t>a\u2264b</m:t></m:r>")
        assert omml_to_latex(elem) == r"a\leqb"


class TestRobustness:
    """Malformed OMML and unknown-operator fallbacks should degrade gracefully."""

    def test_fraction_missing_numerator(self):
        elem = _wrap_in_omath(
            "<m:f><m:den><m:r><m:t>b</m:t></m:r></m:den></m:f>"
        )
        # Empty numerator, no exception.
        assert omml_to_latex(elem) == r"\frac{}{b}"

    def test_fraction_missing_denominator(self):
        elem = _wrap_in_omath(
            "<m:f><m:num><m:r><m:t>a</m:t></m:r></m:num></m:f>"
        )
        assert omml_to_latex(elem) == r"\frac{a}{}"

    def test_superscript_missing_base(self):
        elem = _wrap_in_omath(
            "<m:sSup><m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup>"
        )
        assert omml_to_latex(elem) == "{}^{2}"

    def test_radical_missing_base(self):
        elem = _wrap_in_omath("<m:rad></m:rad>")
        assert omml_to_latex(elem) == r"\sqrt{}"

    def test_unknown_nary_operator_preserved(self):
        # \u2A06 (N-ARY SQUARE UNION OPERATOR) is not in our table; the raw
        # Unicode character should survive instead of being rewritten to \int.
        elem = _wrap_in_omath(
            "<m:nary>"
            '<m:naryPr><m:chr m:val="\u2a06"/></m:naryPr>'
            "<m:e><m:r><m:t>x</m:t></m:r></m:e>"
            "</m:nary>"
        )
        assert omml_to_latex(elem) == "\u2a06 x"


class TestExtractFromDocx:
    """End-to-end extraction from in-memory DOCX archives."""

    def test_extracts_single_equation(self, tmp_path):
        docx = _make_docx(
            f"<m:oMath {NS_DECL}>"
            "<m:f>"
            "<m:num><m:r><m:t>1</m:t></m:r></m:num>"
            "<m:den><m:r><m:t>2</m:t></m:r></m:den>"
            "</m:f>"
            "</m:oMath>"
        )
        path = tmp_path / "single.docx"
        path.write_bytes(docx)
        result = extract_omml_equations(path)
        assert len(result) == 1
        assert result[0]["text"] == r"\frac{1}{2}"
        assert result[0]["text_format"] == "latex"
        assert result[0]["index"] == 0

    def test_extracts_multiple_equations_in_order(self, tmp_path):
        eq1 = f"<m:oMath {NS_DECL}><m:r><m:t>a+b</m:t></m:r></m:oMath>"
        eq2 = (
            f"<m:oMath {NS_DECL}>"
            "<m:sSup>"
            "<m:e><m:r><m:t>x</m:t></m:r></m:e>"
            "<m:sup><m:r><m:t>2</m:t></m:r></m:sup>"
            "</m:sSup>"
            "</m:oMath>"
        )
        path = tmp_path / "two.docx"
        path.write_bytes(_make_docx(eq1 + eq2))
        result = extract_omml_equations(path)
        assert [eq["text"] for eq in result] == ["a+b", "{x}^{2}"]
        assert [eq["index"] for eq in result] == [0, 1]

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            extract_omml_equations(tmp_path / "nope.docx")

    def test_invalid_zip_raises_value_error(self, tmp_path):
        path = tmp_path / "bad.docx"
        path.write_bytes(b"not a zip")
        with pytest.raises(ValueError, match="not a valid ZIP"):
            extract_omml_equations(path)

    def test_zip_without_document_xml_raises_value_error(self, tmp_path):
        path = tmp_path / "empty.docx"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("other.xml", "<root/>")
        with pytest.raises(ValueError, match="word/document.xml"):
            extract_omml_equations(path)


class TestEnrichContentList:
    """Tests for the content-list enrichment helper."""

    def test_appends_extracted_equations(self, tmp_path):
        path = tmp_path / "doc.docx"
        path.write_bytes(
            _make_docx(
                f"<m:oMath {NS_DECL}>"
                "<m:f>"
                "<m:num><m:r><m:t>p</m:t></m:r></m:num>"
                "<m:den><m:r><m:t>q</m:t></m:r></m:den>"
                "</m:f>"
                "</m:oMath>"
            )
        )
        original = [
            {"type": "text", "text": "Hello", "page_idx": 0},
            {"type": "text", "text": "World", "page_idx": 3},
        ]
        enriched = enrich_content_list_with_docx_equations(original, path)
        # Original list is untouched.
        assert len(original) == 2
        # Enriched list has one extra equation block at the end with the
        # last page index inherited.
        assert len(enriched) == 3
        eq_block = enriched[-1]
        assert eq_block["type"] == "equation"
        assert eq_block["text"] == r"\frac{p}{q}"
        assert eq_block["text_format"] == "latex"
        assert eq_block["page_idx"] == 3
        assert eq_block["_source"] == "omml_extractor"

    def test_deduplicates_against_existing_equations(self, tmp_path):
        path = tmp_path / "dup.docx"
        path.write_bytes(
            _make_docx(f"<m:oMath {NS_DECL}><m:r><m:t>x+y</m:t></m:r></m:oMath>")
        )
        original = [
            {
                "type": "equation",
                "text": "x+y",
                "text_format": "latex",
                "page_idx": 0,
            },
        ]
        enriched = enrich_content_list_with_docx_equations(original, path)
        # No new block added because the equation is already present.
        assert len(enriched) == 1
        assert enriched[0]["text"] == "x+y"

    def test_can_disable_deduplication(self, tmp_path):
        path = tmp_path / "dup2.docx"
        path.write_bytes(
            _make_docx(f"<m:oMath {NS_DECL}><m:r><m:t>x+y</m:t></m:r></m:oMath>")
        )
        original = [
            {
                "type": "equation",
                "text": "x+y",
                "text_format": "latex",
                "page_idx": 0,
            },
        ]
        enriched = enrich_content_list_with_docx_equations(
            original, path, deduplicate_existing_equations=False
        )
        assert len(enriched) == 2
        assert enriched[1]["_source"] == "omml_extractor"

    def test_empty_extraction_returns_copy(self, tmp_path):
        # DOCX with no equations.
        path = tmp_path / "noeq.docx"
        path.write_bytes(_make_docx(""))
        original = [{"type": "text", "text": "Hi", "page_idx": 0}]
        enriched = enrich_content_list_with_docx_equations(original, path)
        assert enriched == original
        # Should be a copy, not the same list object.
        assert enriched is not original
