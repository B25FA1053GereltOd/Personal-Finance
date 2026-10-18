"""Generate only invented test data in the observed workbook structure."""

from pathlib import Path

from openpyxl import Workbook

from app.parsers.khan import HEADERS


def create_fixture(path: Path) -> None:
    book = Workbook()
    try:
        sheet = book.active
        sheet.title = "Synthetic Khan"
        sheet.append([
            "Хэвлэсэн огноо:", "10/20/2026", "Синтетик дансны дэлгэрэнгүй хуулга",
            "Хэрэглэгч:", "Туршилт Номин", "Интервал:", "2026/10/01", "-", "2026/10/31",
            "Валют:", "MNT", "IBAN: MN00000000000000000000",
        ])
        sheet.append(HEADERS)
        sheet.append(["2026-10-05 09:10:11", "0001", 1000, 100.25, 0, 1100.25,
                      "  Сургалтын дэмжлэг — туршилт  ", "00009999"])
        sheet.append(["2026-10-06 10:20:30", "0002", 1100.25, 0, -25.10, 1075.15,
                      "Туршилтын кофе ☕", None])
        sheet.append([None])
        sheet.append(["2026-10-07 11:22:33", "0001", 1075.15, 0.15, 0, 1075.30,
                      "Туршилтын буцаалт", "MN00000000000000000001"])
        sheet.append(["Нийт дүн:", None, None, "100.40", "25.10"])
        path.parent.mkdir(parents=True, exist_ok=True)
        book.save(path)
    finally:
        book.close()


if __name__ == "__main__":
    create_fixture(Path(__file__).parent / "fixtures" / "khan_synthetic.xlsx")
