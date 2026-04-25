"""
OMML (Office Math Markup Language) equation extraction for DOCX documents.

Word stores equations as ``<m:oMath>`` elements inside ``word/document.xml``.
When a DOCX is converted to PDF (e.g. via LibreOffice for the MinerU parser
or via Docling's native pipeline), inline math is typically rasterized to an
image or replaced with a placeholder, so the structured math content is lost
to the downstream RAG pipeline.

This module provides a zero-dependency, pure-stdlib utility to:

1. Open a DOCX as a ZIP archive,
2. Locate every ``<m:oMath>`` / ``<m:oMathPara>`` element in document order,
3. Convert each one to a LaTeX string using a recursive transformer that
   handles the most common OMML constructs (runs, fractions, scripts,
   radicals, n-ary operators, functions, delimiters, matrices, accents,
   and grouping characters), and
4. Optionally merge the extracted equations into an already-parsed
   ``content_list`` (the MinerU-compatible list of content blocks produced
   by :class:`raganything.parser.MineruParser` / :class:`DoclingParser`)
   as ``{"type": "equation", "text": "<latex>", "text_format": "latex", ...}``
   blocks so that downstream multimodal processors can index them.

The LaTeX produced by :func:`omml_to_latex` is intended to be searchable and
human-readable rather than typographically perfect; for unhandled constructs
the converter falls back to the concatenated text content of the element
rather than failing. This is deliberate: the priority for RAG is recall, not
pixel-accurate rendering.

Example
-------
>>> from raganything.omml_extractor import extract_omml_equations
>>> equations = extract_omml_equations("paper.docx")  # doctest: +SKIP
>>> for eq in equations:                              # doctest: +SKIP
...     print(eq["index"], eq["text"])
0 \\frac{a}{b}
1 \\sum_{i=1}^{n} x_{i}^{2}
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# --- XML namespaces used in WordprocessingML / OMML ----------------------
# These are the namespace URIs declared by every Word document part. We use
# them to construct fully qualified tag names so that lookups are robust to
# arbitrary namespace prefix choices in the source XML.
NS = {
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}

_M = "{" + NS["m"] + "}"
_W = "{" + NS["w"] + "}"

# OMML "n-ary" operator characters and their LaTeX equivalents. Word stores
# the operator as a Unicode codepoint inside m:naryPr/m:chr; if the chr
# attribute is absent it defaults to the integral sign (\u222b).
_NARY_OPERATORS: Dict[str, str] = {
    "\u2211": r"\sum",  # SUMMATION
    "\u220f": r"\prod",  # PRODUCT
    "\u2210": r"\coprod",  # COPRODUCT
    "\u222b": r"\int",  # INTEGRAL
    "\u222c": r"\iint",  # DOUBLE INTEGRAL
    "\u222d": r"\iiint",  # TRIPLE INTEGRAL
    "\u222e": r"\oint",  # CONTOUR INTEGRAL
    "\u222f": r"\oiint",  # SURFACE INTEGRAL
    "\u22c3": r"\bigcup",  # N-ARY UNION
    "\u22c2": r"\bigcap",  # N-ARY INTERSECTION
    "\u2a00": r"\bigodot",
    "\u2a01": r"\bigoplus",
    "\u2a02": r"\bigotimes",
}

# A small mapping of Unicode math symbols Word likes to use in m:t runs.
# The set is intentionally minimal; anything not in the table is passed
# through unchanged so that ``\alpha`` and ``α`` both remain searchable.
_SYMBOL_TO_LATEX: Dict[str, str] = {
    "\u00b1": r"\pm",
    "\u00d7": r"\times",
    "\u00f7": r"\div",
    "\u2202": r"\partial",
    "\u2207": r"\nabla",
    "\u221a": r"\sqrt{}",  # bare radical sign (rare; m:rad handles real ones)
    "\u221e": r"\infty",
    "\u2248": r"\approx",
    "\u2260": r"\neq",
    "\u2264": r"\leq",
    "\u2265": r"\geq",
    "\u2192": r"\to",
    "\u21d2": r"\Rightarrow",
    "\u21d4": r"\Leftrightarrow",
    "\u2208": r"\in",
    "\u2209": r"\notin",
    "\u2282": r"\subset",
    "\u2286": r"\subseteq",
    "\u22c5": r"\cdot",
    "\u2026": r"\dots",
}


# --- Public API ----------------------------------------------------------


def extract_omml_equations(
    docx_path: Union[str, Path],
) -> List[Dict[str, Any]]:
    """Extract every OMML equation from a DOCX file in document order.

    Parameters
    ----------
    docx_path:
        Path to a ``.docx`` file. The file is opened read-only as a ZIP
        archive; the path itself is not modified.

    Returns
    -------
    list of dict
        One dict per equation, in document order, with the following keys:

        - ``index`` (int): zero-based position in the equation sequence.
        - ``text`` (str): LaTeX representation of the equation.
        - ``text_format`` (str): always ``"latex"``.
        - ``raw_omml`` (str): the original ``<m:oMath>`` XML, useful for
          callers that want to plug in their own converter.

    Raises
    ------
    FileNotFoundError
        If ``docx_path`` does not exist.
    ValueError
        If the file is not a valid DOCX (no ``word/document.xml``) or its
        XML cannot be parsed.

    Notes
    -----
    Both top-level ``<m:oMath>`` elements and the ``<m:oMath>`` children of
    ``<m:oMathPara>`` (display equations) are returned. Nested ``<m:oMath>``
    elements inside another ``<m:oMath>`` (which Word does not actually
    produce) are skipped to avoid duplicate extraction.
    """
    path = Path(docx_path)
    if not path.exists():
        raise FileNotFoundError(f"DOCX file does not exist: {path}")

    try:
        with zipfile.ZipFile(path, "r") as archive:
            try:
                xml_bytes = archive.read("word/document.xml")
            except KeyError as e:
                raise ValueError(
                    f"{path} does not contain word/document.xml; "
                    "is it a valid DOCX file?"
                ) from e
    except zipfile.BadZipFile as e:
        raise ValueError(f"{path} is not a valid ZIP/DOCX archive") from e

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise ValueError(f"Could not parse word/document.xml in {path}: {e}") from e

    results: List[Dict[str, Any]] = []
    # iter() walks the entire tree in document order, which is exactly what
    # we want: the resulting list is ordered the same way Word renders the
    # equations on screen.
    seen: set = set()
    for elem in root.iter(_M + "oMath"):
        elem_id = id(elem)
        if elem_id in seen:
            continue
        # Skip nested oMath inside another oMath (defensive; Word does not
        # nest oMath, but custom XML manipulation could).
        parent_is_omath = False
        for ancestor in root.iter(_M + "oMath"):
            if ancestor is elem:
                continue
            for child in ancestor.iter(_M + "oMath"):
                if child is elem:
                    parent_is_omath = True
                    break
            if parent_is_omath:
                break
        if parent_is_omath:
            continue

        seen.add(elem_id)
        try:
            latex = omml_to_latex(elem).strip()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(
                "Failed to convert OMML equation #%d to LaTeX: %s. "
                "Falling back to text content.",
                len(results),
                e,
            )
            latex = "".join(elem.itertext()).strip()

        results.append(
            {
                "index": len(results),
                "text": latex,
                "text_format": "latex",
                "raw_omml": ET.tostring(elem, encoding="unicode"),
            }
        )

    logger.debug("Extracted %d OMML equations from %s", len(results), path)
    return results


def enrich_content_list_with_docx_equations(
    content_list: List[Dict[str, Any]],
    docx_path: Union[str, Path],
    *,
    page_idx_key: str = "page_idx",
    deduplicate_existing_equations: bool = True,
) -> List[Dict[str, Any]]:
    """Merge OMML equations extracted from ``docx_path`` into a parsed content list.

    The DOCX → PDF conversion that both the MinerU and Docling parsers rely on
    typically loses inline math. This helper extracts the original OMML
    equations directly from the DOCX file and inserts equation-typed blocks
    into ``content_list`` so they participate in downstream RAG indexing.

    Parameters
    ----------
    content_list:
        A list of MinerU-compatible content blocks as produced by
        :class:`raganything.parser.MineruParser` or
        :class:`raganything.parser.DoclingParser`. The list is *not* mutated;
        a new list is returned.
    docx_path:
        Path to the original ``.docx`` source.
    page_idx_key:
        Name of the page-index field on each block. Defaults to ``"page_idx"``,
        which matches both built-in parsers.
    deduplicate_existing_equations:
        When ``True`` (the default), equations already present in
        ``content_list`` (typically as ``"type": "equation"`` placeholders
        inserted by the parser) whose ``text`` matches an extracted OMML
        equation are kept and skipped. When ``False``, every extracted
        equation is appended even if a duplicate already exists.

    Returns
    -------
    list of dict
        A new content list with the extracted equations appended at the end
        (with ``page_idx`` copied from the last existing block, or 0 if the
        list is empty). Callers that need precise positional placement can
        re-sort or splice the returned list using ``raw_omml`` as a key.

    Notes
    -----
    Positioning equations within a PDF-derived content list is intrinsically
    lossy: the original DOCX paragraphs do not carry page numbers. For now
    the helper appends equations in document order at the tail of the list
    with a synthetic page index. This is sufficient for retrieval (the
    equations become indexable LaTeX text) but not for visual reconstruction.
    Callers needing positional accuracy can post-process the list using the
    ``raw_omml`` field returned by :func:`extract_omml_equations`.

    Limitations
    -----------
    - Deduplication compares the LaTeX ``text`` field exactly. It will
      therefore not match parser-emitted placeholder strings (e.g. ``"[FORMULA]"``)
      nor LaTeX produced by image-based equation OCR in MinerU/Docling, even
      when they semantically refer to the same equation. If a parser already
      emits LaTeX for some equations you may see both versions; pass
      ``deduplicate_existing_equations=False`` and post-process if you need
      a stricter merge policy.
    - All extracted equations are appended at the end of the returned list
      with ``page_idx`` copied from the last existing block (or ``0`` when
      the input is empty). Treat ``page_idx`` on enriched equations as a
      retrieval hint rather than a precise page-level location; use
      ``raw_omml`` to splice back into the correct position when ordering
      matters.
    """
    extracted = extract_omml_equations(docx_path)
    if not extracted:
        return list(content_list)

    existing_equations: set = set()
    if deduplicate_existing_equations:
        for block in content_list:
            if block.get("type") == "equation":
                text = (block.get("text") or "").strip()
                if text:
                    existing_equations.add(text)

    last_page_idx = 0
    if content_list:
        try:
            last_page_idx = int(content_list[-1].get(page_idx_key, 0) or 0)
        except (TypeError, ValueError):
            last_page_idx = 0

    enriched: List[Dict[str, Any]] = list(content_list)
    appended = 0
    for eq in extracted:
        latex = eq["text"].strip()
        if not latex:
            continue
        if deduplicate_existing_equations and latex in existing_equations:
            continue
        enriched.append(
            {
                "type": "equation",
                "img_path": "",
                "text": latex,
                "text_format": "latex",
                page_idx_key: last_page_idx,
                "_source": "omml_extractor",
            }
        )
        appended += 1

    logger.info(
        "Enriched content list with %d/%d OMML equations from %s",
        appended,
        len(extracted),
        docx_path,
    )
    return enriched


# --- OMML → LaTeX recursive transformer ----------------------------------


def omml_to_latex(element: ET.Element) -> str:
    """Convert a single ``<m:oMath>`` element (or any of its children) to LaTeX.

    The function is a small recursive descent transformer. For each known OMML
    construct it emits the canonical LaTeX form; unknown elements fall through
    to their concatenated text content so that callers always get *some*
    searchable representation.

    Parameters
    ----------
    element:
        An :class:`xml.etree.ElementTree.Element` from the OMML namespace.
        Typically the root ``<m:oMath>`` returned by
        :func:`extract_omml_equations`, but any descendant works too.

    Returns
    -------
    str
        A LaTeX string. The result is *not* wrapped in math delimiters
        (``$ ... $`` or ``\\[ ... \\]``); the caller chooses the context.
    """
    return _convert(element)


def _convert(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""

    tag = _local_name(element.tag)
    handler = _HANDLERS.get(tag)
    if handler is not None:
        return handler(element)

    # Generic fallback: concatenate child conversions, then own text.
    parts = [_text_for(element)]
    for child in element:
        parts.append(_convert(child))
        if child.tail:
            parts.append(_escape_text(child.tail))
    return "".join(p for p in parts if p)


def _local_name(qname: str) -> str:
    if "}" in qname:
        return qname.split("}", 1)[1]
    return qname


def _text_for(element: ET.Element) -> str:
    if element.text is None:
        return ""
    return _escape_text(element.text)


def _escape_text(text: str) -> str:
    """Map common Word math symbols to LaTeX commands; pass through the rest."""
    if not text:
        return ""
    out = []
    for ch in text:
        replacement = _SYMBOL_TO_LATEX.get(ch)
        out.append(replacement if replacement is not None else ch)
    return "".join(out)


def _children_by_tag(element: ET.Element, tag: str) -> List[ET.Element]:
    full = _M + tag
    return [c for c in element if c.tag == full]


def _first_child(element: ET.Element, tag: str) -> Optional[ET.Element]:
    children = _children_by_tag(element, tag)
    return children[0] if children else None


def _convert_children(element: Optional[ET.Element]) -> str:
    # Tolerate a missing child element: handlers like _h_fraction or
    # _h_radical pass the result of _first_child() directly here, which can
    # be None when the source DOCX is malformed (a fraction without m:num,
    # a radical without m:e, ...). Returning "" keeps the converter on its
    # recall-over-correctness contract instead of raising.
    if element is None:
        return ""
    parts = []
    for child in element:
        parts.append(_convert(child))
        if child.tail:
            parts.append(_escape_text(child.tail))
    return "".join(parts)


# --- Per-element handlers -------------------------------------------------
#
# Each handler is responsible for producing the LaTeX equivalent of one OMML
# construct and for recursing into its semantically meaningful children.


def _h_omath(element: ET.Element) -> str:
    return _convert_children(element)


def _h_omath_para(element: ET.Element) -> str:
    # Display math container; we just join inner equations with a space.
    return " ".join(_convert(c) for c in _children_by_tag(element, "oMath"))


def _h_run(element: ET.Element) -> str:
    # m:r is a math "run" containing m:t text nodes.
    parts = []
    for t in _children_by_tag(element, "t"):
        parts.append(_text_for(t))
    return "".join(parts)


def _h_text(element: ET.Element) -> str:
    return _text_for(element)


def _h_fraction(element: ET.Element) -> str:
    num = _first_child(element, "num")
    den = _first_child(element, "den")
    return r"\frac{" + _convert_children(num) + "}{" + _convert_children(den) + "}"


def _h_superscript(element: ET.Element) -> str:
    base = _first_child(element, "e")
    sup = _first_child(element, "sup")
    return "{" + _convert_children(base) + "}^{" + _convert_children(sup) + "}"


def _h_subscript(element: ET.Element) -> str:
    base = _first_child(element, "e")
    sub = _first_child(element, "sub")
    return "{" + _convert_children(base) + "}_{" + _convert_children(sub) + "}"


def _h_sub_superscript(element: ET.Element) -> str:
    base = _first_child(element, "e")
    sub = _first_child(element, "sub")
    sup = _first_child(element, "sup")
    return (
        "{"
        + _convert_children(base)
        + "}_{"
        + _convert_children(sub)
        + "}^{"
        + _convert_children(sup)
        + "}"
    )


def _h_pre_sub_superscript(element: ET.Element) -> str:
    # m:sPre — a pre-script: prescripts to the left of the base.
    base = _first_child(element, "e")
    sub = _first_child(element, "sub")
    sup = _first_child(element, "sup")
    return (
        "{}_{"
        + _convert_children(sub)
        + "}^{"
        + _convert_children(sup)
        + "}{"
        + _convert_children(base)
        + "}"
    )


def _h_radical(element: ET.Element) -> str:
    deg = _first_child(element, "deg")
    base = _first_child(element, "e")
    base_latex = _convert_children(base)
    if deg is not None and list(deg):
        return r"\sqrt[" + _convert_children(deg) + "]{" + base_latex + "}"
    return r"\sqrt{" + base_latex + "}"


def _h_nary(element: ET.Element) -> str:
    # m:nary — n-ary operator (sum, integral, etc.). The operator character
    # lives in m:naryPr/m:chr/@m:val; defaults to the integral sign per ECMA-376.
    pr = _first_child(element, "naryPr")
    # ECMA-376 §22.1.2.74: when m:chr is absent the operator defaults to
    # the integral sign. When m:chr is present but its value is not in our
    # LaTeX table, fall back to the original Unicode character rather than
    # silently rewriting it to \int — preserving the symbol keeps the
    # equation searchable for downstream RAG even when the operator is
    # exotic (e.g. \bigsqcup, \bigwedge, custom math fonts).
    op = r"\int"
    if pr is not None:
        chr_elem = _first_child(pr, "chr")
        if chr_elem is not None:
            val = chr_elem.get(_M + "val")
            if val:
                op = _NARY_OPERATORS.get(val, val)
    sub = _first_child(element, "sub")
    sup = _first_child(element, "sup")
    base = _first_child(element, "e")
    out = op
    if sub is not None and list(sub):
        out += "_{" + _convert_children(sub) + "}"
    if sup is not None and list(sup):
        out += "^{" + _convert_children(sup) + "}"
    if base is not None:
        body = _convert_children(base)
        if body:
            out += " " + body
    return out


def _h_function(element: ET.Element) -> str:
    # m:func — applied function such as sin, cos, log, ln. fName provides
    # the function name (typically a m:r run); m:e provides the argument.
    fname = _first_child(element, "fName")
    arg = _first_child(element, "e")
    name = _convert_children(fname).strip() if fname is not None else ""
    arg_latex = _convert_children(arg) if arg is not None else ""
    # If the name matches a known LaTeX command, keep it as a control sequence.
    known = {
        "sin",
        "cos",
        "tan",
        "csc",
        "sec",
        "cot",
        "sinh",
        "cosh",
        "tanh",
        "arcsin",
        "arccos",
        "arctan",
        "log",
        "ln",
        "exp",
        "lim",
        "max",
        "min",
        "sup",
        "inf",
        "det",
        "dim",
        "ker",
    }
    if name in known:
        return f"\\{name}{{{arg_latex}}}"
    return f"{name}({arg_latex})"


def _h_delimiter(element: ET.Element) -> str:
    # m:d — delimited expression. m:dPr/@begChr and @endChr give the actual
    # opening/closing characters; defaults are parentheses.
    pr = _first_child(element, "dPr")
    beg, end, sep = "(", ")", ","
    if pr is not None:
        beg_elem = _first_child(pr, "begChr")
        end_elem = _first_child(pr, "endChr")
        sep_elem = _first_child(pr, "sepChr")
        if beg_elem is not None:
            beg = beg_elem.get(_M + "val", beg)
        if end_elem is not None:
            end = end_elem.get(_M + "val", end)
        if sep_elem is not None:
            sep = sep_elem.get(_M + "val", sep)
    inner = sep.join(_convert_children(e) for e in _children_by_tag(element, "e"))
    return (
        _delim_to_latex(beg, opening=True) + inner + _delim_to_latex(end, opening=False)
    )


def _delim_to_latex(ch: str, *, opening: bool) -> str:
    mapping = {
        "(": "(",
        ")": ")",
        "[": "[",
        "]": "]",
        "{": r"\{",
        "}": r"\}",
        "|": "|",
        "\u2016": r"\|",  # DOUBLE VERTICAL LINE
        "\u27e8": r"\langle",
        "\u27e9": r"\rangle",
        "\u230a": r"\lfloor",
        "\u230b": r"\rfloor",
        "\u2308": r"\lceil",
        "\u2309": r"\rceil",
        "": "." if opening else ".",
    }
    return mapping.get(ch, ch)


def _h_matrix(element: ET.Element) -> str:
    rows = _children_by_tag(element, "mr")
    body = []
    for row in rows:
        cells = [_convert_children(e) for e in _children_by_tag(row, "e")]
        body.append(" & ".join(cells))
    return r"\begin{matrix} " + r" \\ ".join(body) + r" \end{matrix}"


def _h_bar(element: ET.Element) -> str:
    # m:bar — accent bar; pos="top" → overline, pos="bot" → underline.
    pr = _first_child(element, "barPr")
    pos = "top"
    if pr is not None:
        pos_elem = _first_child(pr, "pos")
        if pos_elem is not None:
            pos = pos_elem.get(_M + "val", pos)
    base = _first_child(element, "e")
    inner = _convert_children(base)
    return (r"\overline{" if pos == "top" else r"\underline{") + inner + "}"


def _h_acc(element: ET.Element) -> str:
    # m:acc — accent (hat, tilde, dot, etc.). m:accPr/m:chr gives the char.
    pr = _first_child(element, "accPr")
    chr_val = "\u0302"  # combining circumflex (hat) by default
    if pr is not None:
        chr_elem = _first_child(pr, "chr")
        if chr_elem is not None:
            chr_val = chr_elem.get(_M + "val", chr_val)
    accent = {
        "\u0302": r"\hat",
        "\u0303": r"\tilde",
        "\u0304": r"\bar",
        "\u0307": r"\dot",
        "\u0308": r"\ddot",
        "\u20d7": r"\vec",
        "\u030c": r"\check",
        "\u0306": r"\breve",
    }.get(chr_val, r"\hat")
    base = _first_child(element, "e")
    return accent + "{" + _convert_children(base) + "}"


def _h_group_chr(element: ET.Element) -> str:
    # m:groupChr — group expression with a character on top or bottom (e.g.
    # an over-brace). We emit the most common forms and fall through.
    pr = _first_child(element, "groupChrPr")
    chr_val = ""
    pos = "top"
    if pr is not None:
        chr_elem = _first_child(pr, "chr")
        pos_elem = _first_child(pr, "pos")
        if chr_elem is not None:
            chr_val = chr_elem.get(_M + "val", "")
        if pos_elem is not None:
            pos = pos_elem.get(_M + "val", pos)
    base = _first_child(element, "e")
    inner = _convert_children(base)
    if chr_val == "\u23de":  # TOP CURLY BRACKET
        return r"\overbrace{" + inner + "}"
    if chr_val == "\u23df":  # BOTTOM CURLY BRACKET
        return r"\underbrace{" + inner + "}"
    if pos == "bot":
        return r"\underset{" + chr_val + "}{" + inner + "}"
    return r"\overset{" + chr_val + "}{" + inner + "}"


def _h_lim_low(element: ET.Element) -> str:
    base = _first_child(element, "e")
    lim = _first_child(element, "lim")
    return _convert_children(base) + "_{" + _convert_children(lim) + "}"


def _h_lim_upp(element: ET.Element) -> str:
    base = _first_child(element, "e")
    lim = _first_child(element, "lim")
    return _convert_children(base) + "^{" + _convert_children(lim) + "}"


def _h_box(element: ET.Element) -> str:
    return _convert_children(_first_child(element, "e"))


def _h_phantom(element: ET.Element) -> str:
    return r"\phantom{" + _convert_children(_first_child(element, "e")) + "}"


def _h_pass_through(element: ET.Element) -> str:
    """Default for elements whose semantics are 'recurse on children'."""
    return _convert_children(element)


# Map of OMML local-name → handler. Anything not listed falls through to the
# generic recursive descent in :func:`_convert`, which preserves text content.
_HANDLERS: Dict[str, Any] = {
    "oMath": _h_omath,
    "oMathPara": _h_omath_para,
    "r": _h_run,
    "t": _h_text,
    "f": _h_fraction,
    "sSup": _h_superscript,
    "sSub": _h_subscript,
    "sSubSup": _h_sub_superscript,
    "sPre": _h_pre_sub_superscript,
    "rad": _h_radical,
    "nary": _h_nary,
    "func": _h_function,
    "d": _h_delimiter,
    "m": _h_matrix,
    "bar": _h_bar,
    "acc": _h_acc,
    "groupChr": _h_group_chr,
    "limLow": _h_lim_low,
    "limUpp": _h_lim_upp,
    "box": _h_box,
    "phant": _h_phantom,
    # Pass-through containers that have no LaTeX equivalent of their own.
    "e": _h_pass_through,
    "num": _h_pass_through,
    "den": _h_pass_through,
    "sub": _h_pass_through,
    "sup": _h_pass_through,
    "deg": _h_pass_through,
    "fName": _h_pass_through,
    "lim": _h_pass_through,
    "mr": _h_pass_through,
}


__all__ = [
    "extract_omml_equations",
    "enrich_content_list_with_docx_equations",
    "omml_to_latex",
]
