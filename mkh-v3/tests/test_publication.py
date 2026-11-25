import base64
import copy
import io
import unittest

from ingest import materialize
from knowledge import Evidence, Knowledge, KnowledgeError
from publication import preview
from state import History


def file_body(name, content):
    return {"operation":"draft", "metadata":{"title":"Learning participation","id":"learning-participation",
            "publisher":"Test institute","url":"https://example.org/archive","release":"1","period":"2024",
            "geography":"Test district","license":"CC0","description":"Training records","topics":"school, learning",
            "limitations":"Missing reports are unknown.","update_policy":"Annual"},
            "filename":name, "content":base64.b64encode(content).decode()}


class SourceTransferTest(unittest.TestCase):
    def test_native_table_without_topic_code_and_withdrawn_or_replaced_results(self):
        body = file_body("visits.csv", b"district;visits;code\nWest;17;001\nEast;;002\nEast;23;002\n")
        source = materialize(body)
        k = Knowledge(releases=[source])
        self.assertEqual(k.inspect(source["id"])["samples"][0]["code"], "001")
        self.assertEqual(k.discover("participation")[0]["id"],source["id"])
        ledger = Evidence(k, False)
        result = k.query([source["id"]], "SELECT avg(visits) AS mean, count(visits) AS observed FROM observations", ledger)
        self.assertEqual(result["data"]["rows"], [{"mean":20, "observed":2}])
        h = History("test", k, False)
        turn = h.sign("chat","owner",{"prompt":"Use the source", "answer":"twenty", "evidence":[result], "basis":ledger.consulted})
        revised = copy.deepcopy(source)
        revised["records"][0]["visits"] = 99
        for releases in ([], [revised]):
            h = History("test", Knowledge(releases=releases), False)
            self.assertTrue(next(h.accessible("chat","owner",[turn]))["withdrawn"])
        self.assertIn("locator", preview(source)["samples"][0])

    def test_pdf_workbook_and_connection_inputs(self):
        import openpyxl
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        buffer = io.BytesIO()
        writer = PdfWriter()
        for text in ("Institutional review","Source trace on the second page"):
            page = writer.add_blank_page(600,800)
            font = DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),
                                     NameObject("/BaseFont"):NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):font})})
            stream = DecodedStreamObject(); stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = stream
        writer.write(buffer)
        doc = materialize(file_body("review.pdf", buffer.getvalue()))
        k = Knowledge(releases=[doc]); ledger = Evidence(k,False)
        hit = k.search_documents("second page",doc["id"],ledger)[0]
        self.assertEqual(hit["data"]["page"],2); self.assertTrue(hit["url"].endswith("#page=2"))
        wb = openpyxl.Workbook(); wb.active.append(["activity","value"]); wb.active.append(["a",10])
        data = io.BytesIO(); wb.save(data)
        self.assertEqual(materialize(file_body("training.xlsx",data.getvalue()))["records"][0]["value"],10)
        conn = file_body("indicator.json", b'{"adapter":"world_bank_wdi","country_code":"MLI","series":{"TEST.ID":{"label":"Example","unit":"people"}}}')
        self.assertEqual(materialize(conn)["type"], "live")
        with self.assertRaises(KnowledgeError):
            materialize(file_body("other.json", b'{"adapter":"unreviewed"}'))
