from staged_scraper.html.markdown import MarkdownRenderer


HTML = """
<article>
  <h1>Renderer Check</h1>
  <p>A paragraph with a <a href="/docs/link">relative link</a>.</p>
  <pre><code class="language-python">print('hello')</code></pre>
  <table>
    <tr><th>Col A</th><th>Col B</th></tr>
    <tr><td>1</td><td>2</td></tr>
  </table>
</article>
"""


def test_markdown_renderer_preserves_code_tables_and_links() -> None:
    rendered = MarkdownRenderer().render_html(HTML, "https://example.com/base/page")

    assert "# Renderer Check" in rendered
    assert "[relative link](https://example.com/docs/link)" in rendered
    assert "```python" in rendered
    assert "print('hello')" in rendered
    assert "| Col A | Col B |" in rendered
