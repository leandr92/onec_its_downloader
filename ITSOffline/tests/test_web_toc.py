import unittest

from urllib.parse import parse_qsl, urlsplit

from its_web.client import its_login_url, quote_url
from its_web.download import asset_request_url, asset_urls
from its_web.toc import (
    browse_nav_url,
    content_href,
    content_rel,
    parse_nav_items,
    parse_toc,
    relativize_html,
    unique_doc_ids,
)

TOC = """
<ul class="tree top active mixed tid">
  <li id="toc_644_index"><a href="/db/erp25doc/bookmark/Index/Index">Книга</a>
    <ul>
      <li id="toc_645_introduction"><a href="/db/erp25doc/bookmark/Introduction/Introduction">Введение</a>
        <ul>
          <li id="toc_645_about"><a href="/db/erp25doc/bookmark/Introduction/About">О программе</a></li>
        </ul>
      </li>
      <li id="toc_720_purchase"><a href="/db/erp25doc/bookmark/Purchase/Purchase">Закупки</a></li>
    </ul>
  </li>
</ul>
"""


class TocTests(unittest.TestCase):
    def test_tree_and_unique_docs(self) -> None:
        nodes = parse_toc(TOC)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["title"], "Книга")
        self.assertEqual(unique_doc_ids(nodes), ["644", "645", "720"])
        about = nodes[0]["children"][0]["children"][0]
        self.assertEqual(about["title"], "О программе")
        self.assertEqual(about["anchor"], "about")

    def test_content_href_is_first_chapter_file(self) -> None:
        html = (
            '<base href="/db/content/erp25doc/src/закупки.htm">'
            '<script>var x="/db/content/erp25doc/src/index.htm";</script>'
        )
        self.assertEqual(content_href(html, "erp25doc"), "/db/content/erp25doc/src/закупки.htm")
        escaped = r'<base href="\/db\/content\/erp25doc\/src\/index.htm">'
        self.assertEqual(content_href(escaped, "erp25doc"), "/db/content/erp25doc/src/index.htm")
        spaced = (
            '<base href="/db/content/v851doc/src/руководство разработчика/'
            'глава 1. концепция системы.htm">'
        )
        self.assertEqual(
            content_href(spaced, "v851doc"),
            "/db/content/v851doc/src/руководство разработчика/глава 1. концепция системы.htm",
        )

    def test_relativize_keeps_images_next_to_chapter(self) -> None:
        html = '<img src="/db/content/erp25doc/src/_img/a.png?_=1">'
        rewritten = relativize_html(html, "erp25doc", "src/закупки.htm")
        self.assertIn('src="_img/a.png?_=1"', rewritten)
        styled = relativize_html(
            '<link href="/css/its.content.css?_=1">',
            "erp25doc",
            "src/введение.htm",
        )
        self.assertIn('href="../_site/css/its.content.css?_=1"', styled)
        self.assertEqual(relativize_html(styled, "erp25doc", "src/введение.htm"), styled)
        self.assertEqual(content_rel("/db/content/erp25doc/src/_img/a.png", "erp25doc"), "src/_img/a.png")
        self.assertIsNone(content_rel("/db/content/other/src/a.png", "erp25doc"))

    def test_assets_skip_other_chapters(self) -> None:
        html = """
        <link rel="stylesheet" href="/db/content/erp25doc/src/style.css">
        <img src="_img/pic.png">
        <a href="/db/content/erp25doc/src/other.htm">другая глава</a>
        <img src="https://example.com/a.png">
        """
        urls = asset_urls(html, "https://its.1c.ru/db/content/erp25doc/src/закупки.htm")
        self.assertEqual(
            urls,
            [
                "https://its.1c.ru/db/content/erp25doc/src/style.css",
                "https://its.1c.ru/db/content/erp25doc/src/_img/pic.png",
            ],
        )

    def test_platform_nav_list(self) -> None:
        html = """
        <ul class="nav list">
          <li id="nav_f1" class="folder"><a href="/db/v851doc/browse/13/-1/1">Руководство разработчика</a></li>
          <li id="nav_d4" class="doc"><a href="/db/v851doc/content/4/hdoc">Глава 1. Концепция системы</a></li>
        </ul>
        """
        items = parse_nav_items(html)
        self.assertTrue(items[0]["folder"])
        self.assertEqual(items[0]["doc_id"], "")
        self.assertEqual(items[1]["doc_id"], "4")
        self.assertEqual(
            browse_nav_url("v851doc", items[0]["href"]),
            "https://its.1c.ru/db/metadata/v851doc/nav_list/13/-1/1_",
        )

    def test_login_url_keeps_service_query(self) -> None:
        query = dict(parse_qsl(urlsplit(its_login_url()).query))
        self.assertIn("provider=login", query["service"])
        self.assertTrue(its_login_url().startswith("https://login.1c.ru/login?"))

    def test_quote_cyrillic_path(self) -> None:
        quoted = quote_url("https://its.1c.ru/db/content/erp25doc/src/закупки.htm")
        self.assertTrue(quoted.isascii())
        self.assertIn("%D0%B7", quoted)
        self.assertTrue(quote_url(quoted).isascii())
        restored = asset_request_url(
            "https://its.1c.ru/db/content/erp25doc/_site/css/its.content.css?_=1"
        )
        self.assertEqual(restored, "https://its.1c.ru/css/its.content.css?_=1")


if __name__ == "__main__":
    unittest.main()
