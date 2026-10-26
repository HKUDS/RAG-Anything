def test_enhanced_markdown_converter_loads_configured_css_file(tmp_path, monkeypatch):
    from raganything import enhanced_markdown

    class FakeMarkdown:
        def __init__(self, **kwargs):
            pass

        def convert(self, content):
            return "<p>synthetic document</p>"

    class FakeMarkdownModule:
        Markdown = FakeMarkdown

    monkeypatch.setattr(
        enhanced_markdown.EnhancedMarkdownConverter,
        "_check_backends",
        lambda self: {},
    )
    monkeypatch.setattr(enhanced_markdown, "MARKDOWN_AVAILABLE", True)
    monkeypatch.setattr(enhanced_markdown, "markdown", FakeMarkdownModule)

    css_file = tmp_path / "custom.css"
    css_content = "body { color: rgb(1, 2, 3); }"
    css_file.write_text(css_content, encoding="utf-8")
    converter = enhanced_markdown.EnhancedMarkdownConverter(
        enhanced_markdown.MarkdownConfig(css_file=str(css_file))
    )

    html = converter._process_markdown_content("# synthetic")

    assert css_content in html
