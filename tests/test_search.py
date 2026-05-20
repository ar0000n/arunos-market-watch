"""Tests for tools/search.py — HTML fetching and text extraction."""

from tools.search import extract_text


class TestExtractText:
    def test_plain_text_passthrough(self):
        assert "hello world" in extract_text("<p>hello world</p>")

    def test_strips_script_blocks(self):
        html = "<p>visible</p><script>var x = 1;</script><p>also visible</p>"
        result = extract_text(html)
        assert "visible" in result
        assert "var x" not in result

    def test_strips_style_blocks(self):
        html = "<p>content</p><style>.foo { color: red; }</style>"
        result = extract_text(html)
        assert "content" in result
        assert "color" not in result

    def test_strips_head_block(self):
        html = "<head><title>Page Title</title></head><body><p>body text</p></body>"
        result = extract_text(html)
        assert "body text" in result
        assert "Page Title" not in result

    def test_strips_noscript_blocks(self):
        html = "<p>main</p><noscript>enable js</noscript>"
        result = extract_text(html)
        assert "main" in result
        assert "enable js" not in result

    def test_nested_script_does_not_leak(self):
        html = "<div><script>function f() { return '<p>fake</p>'; }</script></div><p>real</p>"
        result = extract_text(html)
        assert "real" in result
        assert "fake" not in result
        assert "function" not in result

    def test_empty_html_returns_empty(self):
        assert extract_text("") == ""

    def test_whitespace_only_tags_ignored(self):
        result = extract_text("<p>   </p><p>text</p>")
        assert result.strip() == "text"

    def test_multiple_text_nodes_joined(self):
        result = extract_text("<p>foo</p><p>bar</p>")
        assert "foo" in result
        assert "bar" in result

    def test_real_world_snippet(self):
        html = """
        <html>
          <head><title>Careers</title></head>
          <body>
            <h1>Open Roles</h1>
            <script>trackPageView();</script>
            <p>Product Manager, San Francisco</p>
          </body>
        </html>
        """
        result = extract_text(html)
        assert "Open Roles" in result
        assert "Product Manager" in result
        assert "trackPageView" not in result
        assert "Careers" not in result  # head stripped
