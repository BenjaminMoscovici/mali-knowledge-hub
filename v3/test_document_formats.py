"""Synthetic files only: exact currencies, original locators, limits and isolation."""
import io
import struct
import sys
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from document_formats import chat_excerpt, extract_units, MIME_TYPES
from ingestion import create_job, process_job
from test_ingestion import Database, Embeddings, fixture_pdf

SYNTHETIC_TEXT = 'MKH synthetic format test — Mali, évaluation. USD 12,345.67 and EUR 890.10. No real project facts.'


def fixture_docx(extra=''):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{SYNTHETIC_TEXT}</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Currency</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>USD 12,345.67</w:t></w:r></w:p></w:tc></w:tr></w:tbl>{extra}</w:body></w:document>')
    return output.getvalue()


def fixture_doc(encrypted=False, broken_piece=False):
    """Genuine OLE compound DOC with ANSI + UTF-16 pieces, not renamed RTF.

    Synthetic minimal MS-CFB container and MS-DOC text structures. No external
    documents, macros, binaries, private fixtures or account data.
    """
    free, end, fat_sector = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
    header = bytearray(512)
    header[:8] = bytes.fromhex('D0CF11E0A1B11AE1')
    struct.pack_into('<HHHH', header, 24, 0x3E, 3, 0xFFFE, 9)
    struct.pack_into('<H', header, 32, 6)
    struct.pack_into('<IIIIIIIII', header, 40, 0, 1, 1, 0, 4096, end, 0, end, 0)
    struct.pack_into('<109I', header, 76, 0, *([free]*108))
    fat = [free]*128
    fat[0], fat[1] = fat_sector, end
    for start in [2, 10]:
        for n in range(start, start+7): fat[n] = n+1
        fat[start+7] = end
    def directory(name, kind, start=end, size=0, left=free, right=free, child=free, color=1):
        row = bytearray(128)
        value = (name+'\0').encode('utf-16-le')
        row[:len(value)] = value
        struct.pack_into('<HBBIII', row, 64, len(value), kind, color, left, right, child)
        struct.pack_into('<IQ', row, 116, start, size)
        return row
    dirs = directory('Root Entry', 5, child=1)+directory('WordDocument', 2, 2, 4096, left=2)+directory('1Table', 2, 10, 4096, color=0)+bytearray(128)
    word = bytearray(4096)
    flags = 0x1200 | (0x100 if encrypted else 0)
    struct.pack_into('<HH', word, 0, 0xA5EC, 0xC1)
    struct.pack_into('<H', word, 10, flags)
    struct.pack_into('<H', word, 12, 0xBF)
    struct.pack_into('<H', word, 32, 14)
    struct.pack_into('<H', word, 62, 22)
    first = b'MKH synthetic format test - Mali, '
    last = ('évaluation. USD 12,345.67 and EUR 890.10. No real project facts.\r').encode('utf-16-le')
    position = 1024
    word[position:position+len(first)] = first
    last_position = position+len(first)
    word[last_position:last_position+len(last)] = last
    cp_end = len(first)+len(last)//2
    struct.pack_into('<I', word, 64, last_position+len(last))
    struct.pack_into('<i', word, 76, cp_end)
    struct.pack_into('<H', word, 152, 93)
    plc = struct.pack('<3I', 0, len(first), cp_end)
    plc += struct.pack('<HIH', 0, (position*2)|0x40000000, 0)
    plc += struct.pack('<HIH', 0, 999999 if broken_piece else last_position, 0)
    clx = b'\x02'+struct.pack('<I', len(plc))+plc
    struct.pack_into('<II', word, 418, 0, len(clx))
    return bytes(header)+struct.pack('<128I', *fat)+bytes(dirs)+bytes(word)+clx.ljust(4096, b'\0')


def fixture_odt():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
        archive.writestr('content.xml', f'<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text><text:p>{SYNTHETIC_TEXT}</text:p></office:text></office:body></office:document-content>')
    return output.getvalue()


class DocumentFormatsTests(unittest.TestCase):
    def test_docx_preserves_text_table_currency_and_original_locators(self):
        units, quality = extract_units('résumé.DOCX', fixture_docx())
        self.assertEqual(units[0].text, SYNTHETIC_TEXT)
        self.assertEqual(units[1].text, 'Currency | USD 12,345.67')
        self.assertEqual(units[1].location, 'Body table 1, row 1')
        self.assertTrue(all(u.page is None for u in units))
        self.assertEqual(quality['format'], 'docx')

    def test_binary_doc_unicode_ansi_pieces_and_currency(self):
        raw = fixture_doc()
        self.assertEqual(raw[:8], bytes.fromhex('D0CF11E0A1B11AE1'))
        units, quality = extract_units('test.doc', raw)
        text = '\n'.join(u.text for u in units)
        self.assertIn('Mali, évaluation. USD 12,345.67 and EUR 890.10.', text)
        self.assertEqual(units[0].location, 'Body paragraph 1')
        self.assertEqual(quality['format'], 'doc')
        self.assertTrue(quality['warnings'])

    def test_encrypted_and_corrupt_doc_rejected(self):
        for raw in [fixture_doc(encrypted=True), fixture_doc(broken_piece=True), b'not a document']:
            with self.subTest(raw_length=len(raw)), self.assertRaises(ValueError):
                extract_units('bad.doc', raw)

    def test_odt_rtf_text_and_pdf(self):
        cases = [('test.odt', fixture_odt()), ('test.rtf', b'{\\rtf1\\ansi Test Mali \\u233?valuation USD 12,345.67\\par Funding EUR 890.10}'),
                 ('test.txt', SYNTHETIC_TEXT.encode()), ('test.md', SYNTHETIC_TEXT.encode()),
                 ('test.csv', b'actor,currency,amount\nSynthetic,USD,12345.67'),
                 ('test.tsv', b'actor\tcurrency\tamount\nSynthetic\tEUR\t890.10'), ('test.pdf', fixture_pdf())]
        for name, raw in cases:
            with self.subTest(name=name):
                units, quality = extract_units(name, raw)
                self.assertTrue(units)
                self.assertEqual(quality['format'], name.split('.')[-1])
                self.assertTrue(all(u.page is not None for u in units) if name.endswith('pdf') else all(u.page is None for u in units))

    def test_text_encoding_rejects_binary_and_retains_accents(self):
        self.assertEqual(extract_units('test.txt', SYNTHETIC_TEXT.encode('utf-16'))[0][0].text, SYNTHETIC_TEXT)
        for raw in [b'a\0b', b'\xff\xff', b'']:
            with self.assertRaises(ValueError): extract_units('test.txt', raw)

    def test_archive_limits_xml_entities_extension_and_password(self):
        for filename, raw in [('test.exe', b'xx'), ('test.docx', b'password protected'), ('test.pdf', b'not PDF')]:
            with self.assertRaises(ValueError): extract_units(filename, raw)
        extra = '<w:p><w:r><w:t>ok</w:t></w:r></w:p>'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('word/document.xml', b'<!DOCTYPE root [<!ENTITY a "secret">]><root/>')
        with self.assertRaisesRegex(ValueError, 'entity'): extract_units('test.docx', buffer.getvalue())
        with patch('document_formats.MAX_EXPANDED', 20):
            with self.assertRaises(ValueError): extract_units('test.docx', fixture_docx(extra))

    def test_tracked_changes_and_field_instructions_do_not_become_text(self):
        extra = '<w:p><w:del><w:r><w:delText>DELETED VALUE</w:delText></w:r></w:del><w:ins><w:r><w:t>CURRENT VALUE</w:t></w:r></w:ins><w:r><w:instrText>FETCH SECRET URL</w:instrText></w:r></w:p>'
        units, quality = extract_units('test.docx', fixture_docx(extra))
        text = '\n'.join(u.text for u in units)
        self.assertIn('CURRENT VALUE', text)
        self.assertNotIn('DELETED VALUE', text)
        self.assertNotIn('FETCH SECRET URL', text)
        self.assertIn('Tracked changes', ' '.join(quality['warnings']))

    def test_long_chat_document_bounded_relevant_and_explicitly_partial(self):
        text = ('General background ' * 200 + '\n') * 3 + 'Relevant funding EUR 890.10 and USD 12,345.67.\n'
        result = chat_excerpt('test.txt', text.encode(), 'What funding in EUR and USD?', limit=300)
        self.assertIn('Relevant funding EUR 890.10 and USD 12,345.67.', result['text'])
        self.assertLessEqual(len(result['text']), 300)
        self.assertFalse(result['complete_text'])
        self.assertFalse(result['original_saved'])

    def test_administration_retains_private_original_and_nullable_locations(self):
        for name, raw in [('test.docx', fixture_docx()), ('test.doc', fixture_doc()), ('test.odt', fixture_odt()), ('test.txt', SYNTHETIC_TEXT.encode())]:
            with self.subTest(name=name):
                db = Database()
                with patch.object(db.storage, 'upload', wraps=db.storage.upload) as upload:
                    job = create_job(db, name, raw, 'synthetic-admin')
                    self.assertEqual(upload.call_args.args[2]['content-type'], MIME_TYPES[name.split('.')[-1]])
                published = process_job(db, SimpleNamespace(embeddings=Embeddings()), job)
                records = db.published[published]
                self.assertTrue(all(r['page_number'] is None and r['section_title'] for r in records))
                self.assertIn(raw, db.originals.values())
                self.assertEqual(db.jobs[job]['quality']['pages'], 0)
                self.assertEqual(db.jobs[job]['status'], 'ready')

    def test_broken_office_never_publishes(self):
        db = Database()
        job = create_job(db, 'broken.docx', b'PKbroken archive', 'synthetic-admin')
        with self.assertRaises(ValueError): process_job(db, SimpleNamespace(embeddings=Embeddings()), job)
        self.assertEqual(db.published, {})
        self.assertEqual(db.jobs[job]['status'], 'failed')

    def test_long_original_filename_retains_format_and_processes(self):
        db = Database()
        job = create_job(db, 'long_original_name_' * 20 + '.docx', fixture_docx(), 'synthetic-admin')
        self.assertLessEqual(len(db.jobs[job]['filename']), 120)
        self.assertTrue(db.jobs[job]['filename'].endswith('.docx'))
        process_job(db, SimpleNamespace(embeddings=Embeddings()), job)
        self.assertEqual(db.jobs[job]['status'], 'ready')


class AttachmentAPITests(unittest.TestCase):
    def setUp(self):
        from starlette.testclient import TestClient
        import web_api
        self.client = TestClient(web_api.app, base_url='http://localhost')  # No lifespan or network.
        self.headers = {'Origin': 'http://localhost', 'Content-Type': 'application/octet-stream', 'X-MKH-Filename': 'test.docx'}

    def test_guest_upload_is_local_transient_and_never_calls_research(self):
        with patch('web_api.auth_client', side_effect=AssertionError('No auth or storage')), patch('ingestion.create_job', side_effect=AssertionError('No corpus writes')), patch('openai.OpenAI', side_effect=AssertionError('No provider calls')):
            response = self.client.post('/api/attachments/extract', content=fixture_docx(), headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn(SYNTHETIC_TEXT, response.json()['text'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertFalse(response.json()['original_saved'])

    def test_cross_origin_and_oversize_and_bad_file_rejected(self):
        wrong = dict(self.headers, Origin='https://unrelated.example')
        self.assertEqual(self.client.post('/api/attachments/extract', content=fixture_docx(), headers=wrong).status_code, 403)
        large = dict(self.headers, **{'Content-Length': str(6*1024*1024)})
        self.assertEqual(self.client.post('/api/attachments/extract', content=b'x', headers=large).status_code, 413)
        self.assertEqual(self.client.post('/api/attachments/extract', content=b'PKbroken', headers=self.headers).status_code, 422)

    def test_two_guests_do_not_share_attachment_text(self):
        first = self.client.post('/api/attachments/extract', content=fixture_docx(), headers=self.headers)
        second = self.client.post('/api/attachments/extract', content=b'Another anonymous synthetic guest text', headers=dict(self.headers, **{'X-MKH-Filename':'other.txt'}))
        self.assertNotIn('USD 12,345.67', second.json()['text'])
        self.assertNotIn('Another anonymous', first.json()['text'])


if __name__ == '__main__':
    unittest.main()
