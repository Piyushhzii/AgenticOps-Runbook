import io
import os
import tempfile
import unittest

from docx import Document
from openpyxl import Workbook

from app.services.document_parser import DocumentParseError, parse_source


class DocumentParserTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, name, data: bytes):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_text_and_markdown(self):
        path = self._write("a.md", b"# Title\n\n\n\n1. Ask for ID")
        self.assertEqual(parse_source(path), "# Title\n\n1. Ask for ID")

    def test_html_drops_scripts(self):
        path = self._write("a.html", b"<html><head><title>x</title></head><body>"
                                     b"<script>evil()</script><ul><li>Check status</li></ul></body></html>")
        text = parse_source(path)
        self.assertIn("- Check status", text)
        self.assertNotIn("evil", text)

    def test_docx_paragraphs_and_tables(self):
        document = Document()
        document.add_paragraph("Ask for the transaction ID")
        table = document.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = "Pending"
        table.rows[0].cells[1].text = "Wait 10 minutes"
        buffer = io.BytesIO()
        document.save(buffer)
        text = parse_source(self._write("a.docx", buffer.getvalue()))
        self.assertIn("Ask for the transaction ID", text)
        self.assertIn("Pending | Wait 10 minutes", text)

    def test_xlsx_rows(self):
        workbook = Workbook()
        workbook.active.append(["Step", "Action"])
        workbook.active.append([1, "Check gateway"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        self.assertIn("1 | Check gateway", parse_source(self._write("a.xlsx", buffer.getvalue())))

    def test_unsupported_and_empty_are_rejected(self):
        with self.assertRaisesRegex(DocumentParseError, "Unsupported"):
            parse_source(self._write("a.exe", b"MZ"))
        with self.assertRaisesRegex(DocumentParseError, "No extractable text"):
            parse_source(self._write("a.txt", b"   \n"))

    def test_corrupt_document_is_reported(self):
        with self.assertRaisesRegex(DocumentParseError, "Could not parse"):
            parse_source(self._write("a.pdf", b"not a pdf"))
