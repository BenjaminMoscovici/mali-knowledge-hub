# V3 live intake fixtures — 2026-09-29

These public-source documents are reserved for the isolated V3 Render intake
test. Do not upload the rasterized derivative of the HAC appeal; the original
mid-year report is already image-only and provides a stronger OCR test.

| Case | Source | SHA-256 | Local preflight |
| --- | --- | --- | --- |
| V3-PDF | [UNICEF Mali 2026 Humanitarian Action for Children](https://www.unicef.org/media/179331/file/2026-HAC-Mali.pdf) | `2e81ab628659fbb2f658c647296d39d9221ded765f8f83a4cc8a66fbf6977a9b` | 6 pages, 30,751 chunk characters, 17 chunks, no OCR |
| V3-OCR | [UNICEF Mali Humanitarian Situation Report No. 2, January–June 2026](https://www.unicef.org/media/183456/file/Mali-Humanitarian-Situation-Report%20No.2%28Mid-Year%29%2C30-June-2026.pdf.pdf) | `fb9cd539793c1d4876f16b79eeeaf2ee46d007d0a7f8f0ba60485fda007f1c9b` | 11 image-only pages; local Tesseract OCR extracted 53,743 characters into 33 chunks in 44 seconds |
| V3-BROKEN | Locally generated malformed PDF (`%PDF-1.7` header and no valid objects) | `4f94c18014dc1b0125726f70075e9f56f41bcf1c9cc43aaa77199136bd83f65b` | MuPDF rejects opening; expected failed job and zero public chunks |

Confirm the readable and scanned jobs reach `ready`, metadata and page numbers
are inspectable, and distinctive passages can be found with cited source pages.
For the broken file, confirm a retained original and failed job, with no
searchable chunks. The live results, cost and latency belong in the milestone
report, not in this preflight manifest.
