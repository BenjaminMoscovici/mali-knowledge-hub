"""Local, bounded text extraction. Files are data; never execute or fetch links.

Word locators are body paragraphs/table rows, not invented printed pages.
Legacy Word text follows Microsoft's MS-DOC 2.4.1 piece-table algorithm.
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_BYTES = 20 * 1024 * 1024
MAX_EXPANDED = 40 * 1024 * 1024
MAX_TEXT = 1_000_000
MAX_UNITS = 20_000
MIME_TYPES = {
    'pdf': 'application/pdf', 'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'odt': 'application/vnd.oasis.opendocument.text', 'rtf': 'application/rtf',
    'txt': 'text/plain', 'md': 'text/markdown', 'csv': 'text/csv',
    'tsv': 'text/tab-separated-values',
}
SUPPORTED_EXTENSIONS = tuple(MIME_TYPES)


@dataclass(frozen=True)
class TextUnit:
    location: str
    text: str
    page: int | None = None


def document_format(filename, raw):
    extension = Path(filename).suffix.lower().lstrip('.')
    if extension not in MIME_TYPES:
        raise ValueError('Supported formats: PDF, DOC, DOCX, ODT, RTF, TXT, MD, CSV and TSV.')
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('Choose a nonempty document smaller than 20 MB.')
    if extension == 'pdf' and not raw.startswith(b'%PDF-'):
        raise ValueError('The file is not a valid PDF.')
    if extension in {'docx', 'odt'} and not raw.startswith(b'PK'):
        raise ValueError('The file is not a readable Office document; remove password protection first.')
    if extension == 'doc' and not (raw.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1') or raw.lstrip().startswith(b'{\\rtf')):
        raise ValueError('The file is not a Word 97–2003 DOC. Save older Word files as DOCX.')
    if extension == 'rtf' and not raw.lstrip().startswith(b'{\\rtf'):
        raise ValueError('The file is not valid RTF.')
    return extension


def _xml(raw):
    # ElementTree does not fetch external entities; additionally reject DTDs.
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('A document XML part exceeds the processing limit. Split the document first.')
    if re.search(br'<!\s*(?:DOCTYPE|ENTITY)', raw.replace(b'\x00', b''), re.I):
        raise ValueError('Documents containing XML entity declarations are unsupported.')
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError('The document contains malformed XML.') from None


def _archive(raw):
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        items = archive.infolist()
        if (len(items) > 2000 or len({item.filename for item in items}) != len(items)
                or sum(item.file_size for item in items) > MAX_EXPANDED
                or any(item.flag_bits & 1 for item in items)):
            archive.close()
            raise ValueError('The document archive is encrypted, duplicated or too large to extract.')
        return archive
    except zipfile.BadZipFile:
        raise ValueError('The document archive is damaged.') from None


def _tag(node):
    return node.tag.rsplit('}', 1)[-1]


def _word_text(node):
    pieces = []
    def visit(current):
        tag = _tag(current)
        if tag in {'del', 'moveFrom', 'instrText', 'delText'}:
            return
        if tag == 't':
            pieces.append(current.text or '')
        elif tag == 'tab':
            pieces.append('\t')
        elif tag in {'br', 'cr'}:
            pieces.append('\n')
        else:
            for child in current:
                visit(child)
    visit(node)
    return ''.join(pieces).strip()


def _docx(raw):
    units, warnings = [], ['Body text and tables extracted; images, comments and headers are not included.']
    with _archive(raw) as archive:
        if 'word/document.xml' not in archive.namelist():
            raise ValueError('This is not a DOCX Word document.')
        if any(name.lower().endswith('vbaproject.bin') for name in archive.namelist()):
            raise ValueError('Macro-enabled documents are unsupported. Save a macro-free DOCX.')
        document = _xml(archive.read('word/document.xml'))
        if document.tag not in {'{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document',
                                '{http://purl.oclc.org/ooxml/wordprocessingml/main}document'}:
            raise ValueError('The DOCX has an invalid Word document structure.')
        body = next((n for n in document if _tag(n) == 'body'), None)
        if body is None:
            raise ValueError('The Word document has no body.')
        # Descendant body paragraphs include content controls/text boxes; table
        # paragraphs keep their row/cell identity and are never duplicated.
        paragraph = table = 0
        def walk(node):
            nonlocal paragraph, table
            tag = _tag(node)
            if tag in {'del', 'moveFrom'}:
                return
            if tag == 'p':
                paragraph += 1
                units.append(TextUnit(f'Body paragraph {paragraph}', _word_text(node)))
            elif tag == 'tbl':
                table += 1
                current_table = table
                rows = [n for n in node if _tag(n) == 'tr']
                for row_number, row in enumerate(rows, 1):
                    cells = [n for n in row if _tag(n) == 'tc']
                    value = ' | '.join('\n'.join(_word_text(p) for p in cell.iter() if _tag(p) == 'p') for cell in cells)
                    units.append(TextUnit(f'Body table {current_table}, row {row_number}', value))
            else:
                for child in node:
                    walk(child)
        walk(body)
        if any(_tag(n) in {'del', 'ins', 'moveFrom', 'moveTo'} for n in body.iter()):
            warnings.append('Tracked changes use the current text: insertions included, deletions excluded.')
        if any(_tag(n) == 'altChunk' for n in body.iter()):
            raise ValueError('Word files with embedded alternative documents must be saved as a flattened DOCX or PDF.')
        for part, label in [('word/footnotes.xml', 'Footnote'), ('word/endnotes.xml', 'Endnote')]:
            if part in archive.namelist():
                root = _xml(archive.read(part))
                for note in root:
                    identifier = next((v for k, v in note.attrib.items() if k.endswith('}id')), '')
                    if not identifier.isdigit():
                        continue
                    for ordinal, p in enumerate((p for p in note.iter() if _tag(p) == 'p'), 1):
                        units.append(TextUnit(f'{label} {identifier}, paragraph {ordinal}', _word_text(p)))
    return units, warnings


def _odt(raw):
    units = []
    with _archive(raw) as archive:
        if 'content.xml' not in archive.namelist() or archive.read('mimetype') != b'application/vnd.oasis.opendocument.text':
            raise ValueError('This is not an ODT text document.')
        root = _xml(archive.read('content.xml'))
        body = next((n for n in root.iter() if _tag(n) == 'body'), None)
        if body is None:
            raise ValueError('The ODT document has no body.')
        def text(node):
            pieces = [node.text or '']
            for child in node:
                tag = _tag(child)
                if tag == 's':
                    count = int(next((v for k, v in child.attrib.items() if k.endswith('}c')), '1'))
                    pieces.append(' ' * min(count, 100))
                elif tag == 'tab': pieces.append('\t')
                elif tag == 'line-break': pieces.append('\n')
                elif tag not in {'annotation', 'tracked-changes'}: pieces.append(text(child))
                pieces.append(child.tail or '')
            return ''.join(pieces)
        def walk(node):
            if _tag(node) in {'annotation', 'tracked-changes'}: return
            if _tag(node) in {'p', 'h'}:
                units.append(TextUnit(f'Body paragraph {len(units)+1}', text(node).strip()))
            else:
                for child in node: walk(child)
        walk(body)
    return units, ['Text extracted; images, annotations and page layout are not included.']


def _legacy_doc(raw):
    import olefile
    if raw.lstrip().startswith(b'{\\rtf'):
        return _rtf(raw)
    def integer(buffer, offset, fmt):
        size = struct.calcsize(fmt)
        if offset < 0 or offset + size > len(buffer):
            raise ValueError('The DOC file has a truncated structure.')
        return struct.unpack_from(fmt, buffer, offset)[0]
    with olefile.OleFileIO(io.BytesIO(raw), raise_defects=olefile.DEFECT_INCORRECT) as ole:
        if ole.exists('EncryptedPackage') or not ole.exists('WordDocument'):
            raise ValueError('The DOC is encrypted or is not a Word document.')
        if any(ole.get_size(name) > MAX_BYTES for name in ole.listdir()):
            raise ValueError('A DOC stream exceeds the extraction limit.')
        word = ole.openstream('WordDocument').read()
        if integer(word, 0, '<H') != 0xA5EC or integer(word, 2, '<H') not in {0xC1, 0xD9, 0x101, 0x10C, 0x112}:
            raise ValueError('Save this older Word file as DOCX or PDF before uploading.')
        flags = integer(word, 10, '<H')
        if flags & 0x100:
            raise ValueError('Remove password protection from the Word document before uploading.')
        table_name = '1Table' if flags & 0x200 else '0Table'
        if not ole.exists(table_name):
            raise ValueError('The DOC piece table is missing.')
        table = ole.openstream(table_name).read()
        if integer(word, 32, '<H') != 14 or integer(word, 62, '<H') != 22:
            raise ValueError('The DOC header is malformed.')
        body_length = integer(word, 76, '<i')
        if not 0 < body_length <= MAX_TEXT:
            raise ValueError('The DOC text is empty or exceeds the extraction limit.')
        offset, size = integer(word, 418, '<I'), integer(word, 422, '<I')
        if size < 5 or offset + size > len(table):
            raise ValueError('The DOC piece table is truncated.')
        clx = table[offset:offset+size]
        cursor = 0
        while cursor < len(clx) and clx[cursor] == 1:
            cursor += 3 + integer(clx, cursor+1, '<H')
        if cursor >= len(clx) or clx[cursor] != 2:
            raise ValueError('The DOC piece table cannot be read.')
        length = integer(clx, cursor+1, '<I')
        plc = clx[cursor+5:cursor+5+length]
        if len(plc) != length or length < 16 or (length-4) % 12:
            raise ValueError('The DOC piece table has invalid bounds.')
        count = (length-4)//12
        positions = [integer(plc, n*4, '<I') for n in range(count+1)]
        if positions[0] != 0 or any(a >= b for a, b in zip(positions, positions[1:])) or positions[-1] < body_length:
            raise ValueError('The DOC character positions are invalid.')
        pieces = []
        # MS-DOC FcCompressed uses Latin-1 with a specified subset of Windows
        # punctuation substitutions (0x80 is NOT the cp1252 euro mapping).
        mapping = {n: bytes([n]).decode('cp1252') for n in [0x82,0x83,0x84,0x85,0x86,0x87,0x88,0x89,0x8A,0x8B,0x8C,0x91,0x92,0x93,0x94,0x95,0x96,0x97,0x98,0x99,0x9A,0x9B,0x9C,0x9F]}
        for n in range(count):
            if positions[n] >= body_length: break
            characters = min(positions[n+1], body_length)-positions[n]
            fc = integer(plc, 4*(count+1)+n*8+2, '<I')
            compressed = bool(fc & 0x40000000)
            start = (fc & 0x3FFFFFFF)//2 if compressed else fc & 0x3FFFFFFF
            end = start + characters*(1 if compressed else 2)
            if end > len(word): raise ValueError('DOC text points outside the original file.')
            value = word[start:end]
            pieces.append(''.join(mapping.get(c, chr(c)) for c in value) if compressed else value.decode('utf-16-le'))
        content, field_states = [], []
        for char in ''.join(pieces):
            if char == '\x13': field_states.append(False)
            elif char == '\x14' and field_states: field_states[-1] = True
            elif char == '\x15' and field_states: field_states.pop()
            elif all(field_states): content.append(char)
        if field_states:
            raise ValueError('The DOC contains incomplete field markers.')
        value = ''.join(content).replace('\x07', ' | ').replace('\r', '\n').replace('\x0b', '\n').replace('\x0c', '\n')
        units = [TextUnit(f'Body paragraph {i}', line.strip()) for i, line in enumerate(value.splitlines(), 1)]
    return units, ['DOC main body text and table cells extracted; images, headers, notes and comments are not included.']


def _rtf(raw):
    from striprtf.striprtf import rtf_to_text
    value = rtf_to_text(raw.decode('latin-1'), errors='strict')
    return [TextUnit(f'Text paragraph {i}', line) for i, line in enumerate(value.splitlines(), 1)], ['RTF text extracted; embedded objects and page layout are not included.']


def extract_units(filename, raw):
    """No network, persistence, embeddings, or model calls."""
    kind = document_format(filename, raw)
    try:
        if kind == 'docx': units, warnings = _docx(raw)
        elif kind == 'doc': units, warnings = _legacy_doc(raw)
        elif kind == 'odt': units, warnings = _odt(raw)
        elif kind == 'rtf': units, warnings = _rtf(raw)
        elif kind == 'pdf':
            import fitz
            with fitz.open(stream=raw, filetype='pdf') as pdf:
                if pdf.needs_pass or not 1 <= pdf.page_count <= 80:
                    raise ValueError('Use an unencrypted PDF with at most 80 pages.')
                units, warnings = [], []
                for number, page in enumerate(pdf, 1):
                    value = page.get_text('text').strip()
                    if len(re.sub(r'\W', '', value)) < 10:
                        raise ValueError('This PDF needs OCR. Use administration ingestion for scanned PDFs.')
                    units.append(TextUnit(f'Page {number}', value, number))
        else:
            value = raw.decode('utf-16') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8-sig')
            if '\x00' in value:
                raise ValueError('This is not a readable text document.')
            units = [TextUnit(f'Line {i}', line) for i, line in enumerate(value.splitlines(), 1)]
            warnings = []
        units = [TextUnit(u.location, u.text.strip(), u.page) for u in units if u.text.strip()]
        if not units: raise ValueError('The document contains no extractable text.')
        if len(units) > MAX_UNITS or sum(len(u.text) for u in units) > MAX_TEXT:
            raise ValueError('The extracted text exceeds the processing limit. Split the document first.')
        return units, {'format': kind, 'source_units': len(units), 'warnings': warnings}
    except ValueError:
        raise
    except Exception:
        raise ValueError('The document is damaged or uses an unsupported structure. Save it as DOCX or PDF.') from None


def chat_excerpt(filename, raw, query='', limit=3500):
    units, quality = extract_units(filename, raw)
    words = set(re.findall(r'[^\W_]{3,}', query.casefold())) - {'what','which','about','the','and','for','with','this','that','from','are','was','how'}
    ranked = sorted(range(len(units)), key=lambda i: (-sum(w in units[i].text.casefold() for w in words), i))
    selected, remaining = {}, limit
    for i in ranked:
        unit = units[i]
        prefix = f'[{unit.location}]\n'
        if remaining <= len(prefix)+30: continue
        value = unit.text
        if len(prefix)+len(value)+2 > remaining:
            if selected: continue
            value = value[:remaining-len(prefix)-20].rsplit(' ', 1)[0] + ' [excerpt ends]'
        selected[i] = prefix+value
        remaining -= len(selected[i])+2
    if not selected: raise ValueError('No text excerpt fits. Shorten the question before attaching a file.')
    text = '\n\n'.join(selected[i] for i in sorted(selected))
    complete = len(selected) == len(units) and not any('[excerpt ends]' in v for v in selected.values())
    return {'text': text, **quality, 'complete_text': complete,
            'extracted_characters': sum(len(u.text) for u in units),
            'selected_units': len(selected), 'original_saved': False}
