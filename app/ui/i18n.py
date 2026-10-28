"""Centralized UI translations and local language preference storage."""

import json
import os
import tempfile
import tkinter
from pathlib import Path


DEFAULT_LANGUAGE = "mn"
LANGUAGE_NAMES = {"mn": "Монгол", "en": "English"}

DEFAULT_THEME = "dark"
THEME_NAMES = {"dark": "Бараан горим", "light": "Гэрэлтэй горим"}
THEME_NAMES_EN = {"dark": "Dark mode", "light": "Light mode"}

DEFAULT_EXPENSE_CATEGORIES = (
    ("Сургалтын төлбөр, хичээлийн зардал", "Tuition & Academic Fees"),
    ("Ном, хэвлэл, бичиг хэрэг", "Textbooks, Printing & School Supplies"),
    ("Хоол хүнс", "Food & Groceries"),
    ("Кофе, амттан", "Cafeteria, Coffee & Snacks"),
    ("Түрээс, дотуур байр", "Dormitory / Rent & Utilities"),
    ("Ус, цахилгаан, дулаан", "Utilities (Water, Electricity, Heating)"),
    ("Интернет, гар утас", "Internet & Mobile"),
    ("Тээвэр, такси", "Public Transport / Commuting"),
    ("Програм, дижитал үйлчилгээ", "Software & Digital Subscriptions"),
    ("Эрүүл мэнд, эмчилгээ", "Health & Medical"),
    ("Хувцас, гоо сайхан", "Clothing & Beauty"),
    ("Үзвэр, зугаа цэнгэл", "Social & Entertainment"),
    ("Найз нөхөд, бэлэг", "Friends & Gifts"),
    ("Гэр бүлд үзүүлэх тусламж", "Family Support"),
    ("Гэр ахуйн худалдан авалт", "Household Purchases"),
    ("Банкны шимтгэл", "Bank Fees"),
    ("Өр төлөлт", "Debt Repayment"),
    ("Хуримтлал", "Savings"),
    ("Бусад зардал", "Other expenses"),
)

DEFAULT_INCOME_CATEGORIES = (
    ("Цалин, ажил эрхлэлт", "Earned income (part-time job, freelancing, internship)"),
    ("Фриланс, нэмэлт ажил", "Freelance & Extra Work"),
    ("Тэтгэлэг, грант", "Scholarships / Grants"),
    ("Гэр бүлийн дэмжлэг", "Allowance / Family support"),
    ("Бэлэг, хандив", "Gifts / Donations"),
    ("Буцаан олголт", "Refunds & Reimbursements"),
    ("Хөрөнгө оруулалтын орлого", "Investment Income"),
    ("Бусад орлого", "Other income"),
)

TRANSLATIONS_EN = {
    "Сургалтын төлбөр, хичээлийн зардал": "Tuition & Academic Fees",
    "Ном, хэвлэл, бичиг хэрэг": "Textbooks, Printing & School Supplies",
    "Хоол хүнс": "Food & Groceries",
    "Кофе, амттан": "Cafeteria, Coffee & Snacks",
    "Түрээс, дотуур байр": "Dormitory / Rent & Utilities",
    "Ус, цахилгаан, дулаан": "Utilities (Water, Electricity, Heating)",
    "Интернет, гар утас": "Internet & Mobile",
    "Тээвэр, такси": "Public Transport / Commuting",
    "Програм, дижитал үйлчилгээ": "Software & Digital Subscriptions",
    "Эрүүл мэнд, эмчилгээ": "Health & Medical",
    "Хувцас, гоо сайхан": "Clothing & Beauty",
    "Үзвэр, зугаа цэнгэл": "Social & Entertainment",
    "Найз нөхөд, бэлэг": "Friends & Gifts",
    "Гэр бүлд үзүүлэх тусламж": "Family Support",
    "Гэр ахуйн худалдан авалт": "Household Purchases",
    "Банкны шимтгэл": "Bank Fees",
    "Өр төлөлт": "Debt Repayment",
    "Хуримтлал": "Savings",
    "Бусад зардал": "Other expenses",
    "Цалин, ажил эрхлэлт": "Earned income (part-time job, freelancing, internship)",
    "Фриланс, нэмэлт ажил": "Freelance & Extra Work",
    "Тэтгэлэг, грант": "Scholarships / Grants",
    "Гэр бүлийн дэмжлэг": "Allowance / Family support",
    "Бэлэг, хандив": "Gifts / Donations",
    "Буцаан олголт": "Refunds & Reimbursements",
    "Хөрөнгө оруулалтын орлого": "Investment Income",
    "Бусад орлого": "Other income",
    "Төсөв": "Budget",
    "Сарын төсөв": "Monthly Budget",
    "Төлөвлөсөн дүн": "Planned Amount",
    "Төлөвлөсөн зардал": "Planned Expense",
    "Төлөвлөсөн орлого": "Planned Income",
    "Төсөв нэмэх": "Add budget",
    "Төсөв нэмэх…": "Add budget…",
    "Төсөв засах": "Edit budget",
    "Төсөв засах…": "Edit budget…",
    "Төсөв устгах": "Delete budget",
    "Сар": "Month",
    "Сонгосон сар": "Selected month",
    "Энэ сар": "This month",
    "Бүх сар": "All months",
    "Бүх валют": "All currencies",
    "Идэвхтэй төлөв": "Active status",
    "Төсвийн тэмдэглэл": "Budget note",
    "Төсөв үзэх": "View budgets",
    "Энэ сард бүртгэгдсэн төсөв олдсонгүй.": "No budgets found for this month.",
    "Сонгосон гүйлгээ устгах": "Delete selected transactions",
    "Сонгосон гүйлгээг сэргээх": "Restore selected transactions",
    "Гүйлгээ архивлах": "Archive transactions",
    "Гүйлгээ сэргээх": "Restore transactions",
    "Архивлах": "Archive",
    "Архивлагдсан": "Archived",
    "Идэвхтэй": "Active",
    "Бүгд": "All",
    "Сонгосон гүйлгээний тоо": "Number of selected transactions",
    "Валют тус бүрийн нийт дүн": "Total amount by currency",
    "Огнооны интервал": "Date range",
    "Төлөв / архив": "Status / archive",
}

TRANSLATIONS = {
    # Category Translations
    "Other expenses": "Бусад зардал",
    "Budget": "Төсөв",
    "Budgets": "Төсөв",
    "Monthly Budget": "Сарын төсөв",
    "Monthly budget management": "Сарын төсвийн удирдлага",
    "Planned Amount": "Төлөвлөсөн дүн",
    "Planned amount": "Төлөвлөсөн дүн",
    "Planned Expense": "Төлөвлөсөн зардал",
    "Planned Income": "Төлөвлөсөн орлого",
    "Add budget": "Төсөв нэмэх",
    "Add budget…": "Төсөв нэмэх…",
    "Edit budget": "Төсөв засах",
    "Edit budget…": "Төсөв засах…",
    "Delete budget": "Төсөв устгах",
    "Month": "Сар",
    "Selected month": "Сонгосон сар",
    "This month": "Энэ сар",
    "All months": "Бүх сар",
    "All currencies": "Бүх валют",
    "Active status": "Идэвхтэй төлөв",
    "Budget note": "Төсвийн тэмдэглэл",
    "No budgets found for this month.": "Энэ сард бүртгэгдсэн төсөв олдсонгүй.",
    "No budgets set yet. Click 'Add budget' to create your first monthly budget.": "Төсөв одоогоор бүртгэгдээгүй байна. 'Төсөв нэмэх' товчийг дарж анхны сарын төсвөө үүсгэнэ үү.",
    "View budgets": "Төсөв үзэх",
    "View budget": "Төсөв үзэх",
    "View budgets…": "Төсөв үзэх…",
    "A budget for this month, currency, and category already exists.": "Энэ сар, валют, ангилал дээр төсөв аль хэдийн бүртгэгдсэн байна.",
    "Enter a positive planned amount.": "Эерэг төлөвлөсөн дүн оруулна уу.",
    "Choose a category.": "Ангилал сонгоно уу.",
    "Choose a currency.": "Валют сонгоно уу.",
    "Month must be in YYYY-MM format.": "Сар YYYY-MM форматтай байх ёстой.",
    "Delete selected transactions": "Сонгосон гүйлгээ устгах",
    "Delete selected": "Сонгосон гүйлгээ устгах",
    "Restore selected transactions": "Сонгосон гүйлгээг сэргээх",
    "Restore selected": "Сэргээх",
    "Archive transactions": "Гүйлгээ архивлах",
    "Archive": "Архивлах",
    "Archived": "Архивлагдсан",
    "Status / archive": "Төлөв / архив",
    "Number of selected transactions": "Сонгосон гүйлгээний тоо",
    "Total amount by currency": "Валют тус бүрийн нийт дүн",
    "Date range": "Огнооны интервал",
    "These transactions will be removed from normal reports, dashboard totals, and classification.": "Эдгээр гүйлгээ нь үндсэн тайлан, хяналтын самбар болон ангиллын тооцооноос хасагдана.",
    "Transactions archived.": "Гүйлгээ амжилттай архивлагдлаа.",
    "Transactions restored.": "Гүйлгээ амжилттай сэргээгдлээ.",
    "Restore selected transactions?": "Сонгосон гүйлгээг сэргээх үү?",
    "Other income": "Бусад орлого",
    "Public Transport / Commuting": "Тээвэр, такси",
    "Transportation / Commuting": "Тээвэр, такси",
    "Software & Digital Subscriptions": "Програм, дижитал үйлчилгээ",
    "Tuition & Academic Fees": "Сургалтын төлбөр, хичээлийн зардал",
    "Textbooks, Printing & School Supplies": "Ном, хэвлэл, бичиг хэрэг",
    "Cafeteria, Coffee & Snacks": "Кофе, амттан",
    "Dormitory / Rent & Utilities": "Түрээс, дотуур байр",
    "Social & Entertainment": "Үзвэр, зугаа цэнгэл",
    "Earned income (part-time job, freelancing, internship)": "Цалин, ажил эрхлэлт",
    "Salary & Employment": "Цалин, ажил эрхлэлт",
    "Allowance / Family support": "Гэр бүлийн дэмжлэг",
    "Scholarships / Grants": "Тэтгэлэг, грант",
    "Gifts / Donations": "Бэлэг, хандив",
    "Food & Groceries": "Хоол хүнс",
    "Groceries & Food": "Хоол хүнс",
    "Food": "Хоол хүнс",
    "Utilities (Water, Electricity, Heating)": "Ус, цахилгаан, дулаан",
    "Internet & Mobile": "Интернет, гар утас",
    "Health & Medical": "Эрүүл мэнд, эмчилгээ",
    "Clothing & Beauty": "Хувцас, гоо сайхан",
    "Friends & Gifts": "Найз нөхөд, бэлэг",
    "Family Support": "Гэр бүлд үзүүлэх тусламж",
    "Household Purchases": "Гэр ахуйн худалдан авалт",
    "Bank Fees": "Банкны шимтгэл",
    "Debt Repayment": "Өр төлөлт",
    "Savings": "Хуримтлал",
    "Freelance & Extra Work": "Фриланс, нэмэлт ажил",
    "Freelance & Side work": "Фриланс, нэмэлт ажил",
    "Refunds & Reimbursements": "Буцаан олголт",
    "Refunds": "Буцаан олголт",
    "Investment Income": "Хөрөнгө оруулалтын орлого",
    # Category Management UI
    "Category management": "Ангиллын удирдлага",
    "Category Management": "Ангиллын удирдлага",
    "Manage categories…": "Ангилал удирдах…",
    "Manage categories": "Ангилал удирдах",
    "Categories": "Ангиллууд",
    "Add category": "Ангилал нэмэх",
    "Edit display name": "Харагдах нэр засах",
    "Disable category": "Идэвхгүй болгох",
    "Enable category": "Идэвхжүүлэх",
    "Restore default category": "Үндсэн ангилал сэргээх",
    "Restore default categories": "Үндсэн ангиллуудыг сэргээх",
    "Delete category": "Ангилал устгах",
    "Category name": "Ангиллын нэр",
    "Display name": "Харагдах нэр",
    "Canonical key": "Түлхүүр нэр",
    "Usage": "Ашиглалт",
    "Used in transactions": "Гүйлгээнд ашигласан",
    "Not used": "Ашиглаагүй",
    "Cannot delete category because it is already used. Disable it instead.": (
        "Энэ ангиллыг гүйлгээ эсвэл дүрэмд ашигласан тул устгах боломжгүй. Үүний оронд идэвхгүй болгоно уу."),
    "Select a category first.": "Эхлээд ангилал сонгоно уу.",
    "Category saved.": "Ангилал хадгалагдлаа.",
    "Category deleted.": "Ангилал устгагдлаа.",
    "Default categories restored.": "Үндсэн ангиллууд сэргээгдлээ.",
    "Theme": "Системийн өнгө",
    "System theme": "Системийн өнгө",
    "Light mode": "Гэрэлтэй горим",
    "Dark mode": "Бараан горим",
    "Data location": "Өгөгдлийн байрлал",
    "Backup & privacy": "Нөөцлөлт ба нууцлал",
    "Select application display language": "Програмын харагдах хэлийг сонгох",
    "Select theme mode": "Интерфэйсийн өнгийн горимыг сонгох",
    "Close": "Хаах",
    "Dashboard": "Хураангуй",
    "Transactions": "Гүйлгээнүүд",
    "Import": "Импорт",
    "Review": "Танигдаагүй гүйлгээг ангилах",
    "Rules": "Ангиллын дүрэм",
    "Settings": "Тохиргоо",
    "Import statement": "Хуулга импортлох",
    "Review unknown merchants": "Танигдаагүй гүйлгээг ангилах",
    "Show unclassified transactions": "Ангилаагүй гүйлгээг харуулах",
    "Accounts": "Данснууд",
    "Backup": "Нөөцлөх",
    "Restore": "Сэргээх",
    "Export CSV": "CSV файлаар гаргах",
    "Income": "Орлого",
    "Expense": "Зарлага",
    "Expenses": "Зарлага",
    "Total Revenue": "Нийт орлого",
    "Total Cost": "Нийт зардал",
    "Mapping Table": "Ангиллын зураглал",
    "Classification Mapping Table": "Ангиллын зураглалын хүснэгт",
    "Mapping table updated.": "Зураглалын хүснэгт шинэчлэгдлээ.",
    "Mapping rule saved; currency and source data remain unchanged.": (
        "Зураглалын дүрэм хадгалагдлаа; валют болон эх сурвалжийн өгөгдөл өөрчлөгдөөгүй."),
    "All banks": "Бүх банк",
    "All bank scopes": "Бүх банкны хүрээ",
    "Bank / account scope": "Банк / дансны хүрээ",
    "Field": "Талбар",
    "Condition": "Нөхцөл",
    "Target": "Зорилтот төрөл",
    "Transfer": "Шилжүүлэг",
    "Classification rule": "Ангилсан дүрэм",
    "Merchant rule": "Худалдааны дүрэм",
    "Add bank account": "Банкны данс нэмэх",
    "Other bank formats remain unsupported until verified.": (
        "Бусад банкны хуулгын формат баталгаажих хүртэл импорт дэмжигдэхгүй."),
    "Enter bank name, account name and its statement identifier.": (
        "Банкны нэр, дансны нэр болон хуулгад буй таних дугаарыг оруулна уу."),
    "One-character Contains rules can match many transactions; verify scope and preview carefully.": (
        "Нэг тэмдэгт агуулсан дүрэм олон гүйлгээтэй таарч болзошгүй. Хүрээг шалгаж, урьдчилан харалтыг нягтална уу."),
    "This Contains rule may be broad; verify scope and preview matching transactions.": (
        "Энэ агуулсан нөхцөл өргөн хүрээтэй байж болзошгүй. Хүрээг шалгаж, тохирох гүйлгээг урьдчилан харна уу."),
    "Mapping Table rules classify only matching eligible transactions.": (
        "Зураглалын дүрэм зөвхөн нөхцөлд таарах, боломжтой гүйлгээг ангилна."),
    "Select only eligible transactions to apply; protected rows are excluded.": (
        "Зөвхөн хэрэгжүүлэх боломжтой гүйлгээг сонгоно уу; хамгаалсан мөрүүд хасагдана."),
    "Rule name": "Дүрмийн нэр",
    "Source field": "Талбар",
    "Match operator": "Тааруулах нөхцөл",
    "Match value": "Тааруулах утга",
    "Priority": "Эрэмбэ",
    "pos_id": "POS ID",
    "merchant": "Худалдааны газар",
    "description": "Тайлбар",
    "exact": "Яг тэнцүү",
    "contains": "Агуулсан",
    "starts_with": "Эхэлсэн",
    "ends_with": "Төгссөн",
    "regex": "Regex",
    "Any bank": "Бүх банк",
    "Any account": "Бүх данс",
    "Any direction": "Бүх чиглэл",
    "All rules": "Бүх дүрэм",
    "Search": "Хайх",
    "Add rule": "Дүрэм нэмэх",
    "Edit rule": "Дүрэм засах",
    "Enable / disable": "Идэвхжүүлэх / идэвхгүй болгох",
    "Delete rule": "Дүрэм устгах",
    "Delete mapping rule": "Зураглалын дүрэм устгах",
    "Test rule": "Дүрэм шалгах",
    "Preview matching transactions": "Тохирох гүйлгээг урьдчилан харах",
    "Synthetic test sample": "Синтетик туршилтын жишээ",
    "Add mapping rule": "Зураглалын дүрэм нэмэх",
    "Edit mapping rule": "Зураглалын дүрэм засах",
    "Target kind": "Зорилтот төрөл",
    "Apply to selected": "Сонгосныг хэрэгжүүлэх",
    "Apply to existing eligible rows": "Тохирох өмнөх мөрүүдэд хэрэгжүүлэх",
    "Rule note": "Дүрмийн тэмдэглэл",
    "Preview mapping rule matches": "Дүрмийн тохирлыг урьдчилан харах",
    "Matching transactions": "Тохирсон гүйлгээнүүд",
    "Broad mapping rule warning": "Өргөн хүрээний дүрмийн анхааруулга",
    "The synthetic sample matches this rule.": "Синтетик жишээ энэ дүрэмтэй таарч байна.",
    "The synthetic sample does not match this rule.": "Синтетик жишээ энэ дүрэмтэй таарахгүй байна.",
    "Enable": "Идэвхжүүлэх",
    "Disable": "Идэвхгүй болгох",
    "Category": "Ангилал",
    "Merchant": "Худалдаа, үйлчилгээний газар",
    "Merchant / description": "Худалдаа, үйлчилгээний газар / тайлбар",
    "Apply": "Хэрэгжүүлэх",
    "Cancel": "Цуцлах",
    "Save": "Хадгалах",
    "Delete": "Устгах",
    "Edit": "Засах",
    "Personal Finance Tool": "Хувийн санхүү",
    "Personal Finance": "Хувийн санхүү",
    "Local · Offline": "Төхөөрөмж дээр · Интернэтгүй",
    "Backup…": "Нөөцлөх…",
    "Restore…": "Сэргээх…",
    "Export CSV…": "CSV файлаар гаргах…",
    "Help / About": "Тусламж / Тухай",
    "Open data folder": "Өгөгдлийн хавтас нээх",
    "Page": "Хуудас",
    "Previous": "Өмнөх",
    "Next": "Дараах",
    "Previous page": "Өмнөх хуудас",
    "Next page": "Дараах хуудас",
    "rows": "мөр",
    "transactions": "гүйлгээ",
    "Account": "Данс",
    "Add account…": "Данс нэмэх…",
    "Statement": "Хуулга",
    "Choose .xlsx…": ".xlsx сонгох…",
    "I confirm this is the statement’s account (Khan Bank, MNT).": "Энэ хуулга миний сонгосон Хаан Банкны MNT дансных мөн.",
    "Preview import": "Импортын урьдчилан харах",
    "Commit import": "Импортыг баталгаажуулах",
    "Cancel preview": "Урьдчилан харахыг цуцлах",
    "Rows and duplicate decisions": "Мөрүүд ба давхардлын шийдвэр",
    "Errors and warnings": "Алдаа ба анхааруулга",
    "Status": "Төлөв",
    "Decision": "Шийдвэр",
    "Worksheet": "Ажлын хуудас",
    "Row": "Мөр",
    "Date / time": "Огноо / цаг",
    "Original description": "Эх тайлбар",
    "Amount": "Дүн",
    "Incoming rows — select ambiguous rows to choose Keep or Skip": "Импортлох мөрүүд — тодорхойгүй мөрүүдийг сонгож хадгалах эсвэл алгасах",
    "Keep selected": "Сонгосныг хадгалах",
    "Skip selected": "Сонгосныг алгасах",
    "Clear decision": "Шийдвэр цэвэрлэх",
    "Original row": "Эх мөр",
    "Reference": "Лавлагаа",
    "Balance": "Үлдэгдэл",
    "Possible matches for the first selected row (original imported values)": "Сонгосон эхний мөрийн боломжит тохирол (анхны утгууд)",
    "Severity": "Ноцтой байдал",
    "Column": "Багана",
    "Code": "Код",
    "Message": "Мессеж",
    "All errors must be resolved before any transaction can be committed.": "Алдааг зассаны дараа гүйлгээг импортлоно.",
    "Apply / refresh": "Хэрэгжүүлэх / шинэчлэх",
    "Reset": "Арилгах",
    "Edit selected": "Сонгосныг засах",
    "From (YYYY-MM-DD)": "Эхлэх (YYYY-MM-DD)",
    "To (YYYY-MM-DD)": "Дуусах (YYYY-MM-DD)",
    "Direction": "Чиглэл",
    "Merchant / description search": "Худалдааны газар / тайлбараар хайх",
    "Unclassified only": "Ангилаагүй гүйлгээ",
    "Currency": "Валют",
    "All currencies": "Бүх валют",
    "All accounts": "Бүх данс",
    "All categories": "Бүх ангилал",
    "All directions": "Бүх чиглэл",
    "Debit": "Зарлага",
    "Credit": "Орлого",
    "Zero": "Тэг",
    "Rows per page: ": "Нэг хуудсанд: ",
    "Refresh review": "Жагсаалт шинэчлэх",
    "Expand selected group": "Сонгосон бүлгийг дэлгэх",
    "Skip for later": "Дараа үзэх",
    "Merchant / individual item": "Худалдаа, үйлчилгээний газар / тусдаа мөр",
    "Count": "Тоо",
    "Total MNT": "Нийт MNT",
    "Example description": "Жишээ тайлбар",
    "Unknown merchants and individual items": "Танигдаагүй газрууд ба тусдаа гүйлгээ",
    "Select only the transactions to change (Ctrl/Shift for multiple). No rows are selected automatically.": "Зөвхөн өөрчлөх гүйлгээгээ сонгоно уу (олон сонголтод Ctrl/Shift). Автоматаар сонгохгүй.",
    "ID": "Дугаар",
    "Description": "Тайлбар",
    "Manual protection": "Гараар хамгаалсан",
    "Expanded transactions": "Дэлгэсэн гүйлгээнүүд",
    "Also save a rule for future imports": "Цаашдын импортод дүрэм хадгалах",
    "Preview selected changes": "Сонгосон өөрчлөлтийг харах",
    "Edit selected transaction": "Сонгосон гүйлгээг засах",
    "Refresh rules": "Дүрэм шинэчлэх",
    "Saving or disabling a rule never changes past classifications.": "Дүрэм хадгалах эсвэл идэвхгүй болгох нь өмнөх ангиллыг өөрчлөхгүй.",
    "Bank": "Банк",
    "Exact merchant key": "Худалдааны газрын яг түлхүүр",
    "State": "Төлөв",
    "Saved rules, including disabled rules": "Хадгалсан дүрмүүд, идэвхгүй дүрмүүд орно",
    "Save category / enable (future only)": "Ангилал хадгалах / идэвхжүүлэх (зөвхөн цаашид)",
    "Disable rule": "Дүрэм идэвхгүй болгох",
    "Preview existing eligible rows": "Өмнөх тохирох мөрүүдийг харах",
    "Active": "Идэвхтэй",
    "Disabled": "Идэвхгүй",
    "Page size": "Хуудасны хэмжээ",
    "Dashboard date period": "Хураангуйн хугацаа",
    "Custom from / to (YYYY-MM-DD)": "Огнооны хязгаар (YYYY-MM-DD)",
    "Apply / refresh Dashboard": "Хураангуй хэрэгжүүлэх / шинэчлэх",
    "Net (income - expenses)": "Цэвэр (орлого - зарлага)",
    "Net": "Цэвэр дүн",
    "Unclassified": "Ангилаагүй",
    "Transfers / excluded": "Шилжүүлэг / хассан",
    "Classified totals; currencies are never combined": "Ангилсан дүн; валютыг хооронд нь нэгтгэхгүй",
    "Expenses by category": "Ангиллаар зарлага",
    "Income by category": "Ангиллаар орлого",
    "Monthly income vs expense": "Сарын орлого ба зарлага",
    "Monthly cash flow": "Сарын мөнгөн урсгал",
    "Month": "Сар",
    "Net cash flow": "Цэвэр мөнгөн урсгал",
    "View selected in Transactions": "Сонгосныг гүйлгээнээс харах",
    "All time": "Бүх хугацаа",
    "This month": "Энэ сар",
    "Last month": "Өмнөх сар",
    "This year": "Энэ жил",
    "Custom range": "Өөрийн хугацаа",
    "Language": "Хэл",
    "Mongolian": "Монгол",
    "English": "Англи",
    "Save language": "Хэл хадгалах",
    "Language saved. Close and reopen the application to apply it.": "Хэл хадгаллаа. Өөрчлөлтийг хэрэгжүүлэхийн тулд програмыг хааж дахин нээнэ үү.",
    "Language preference saved.": "Хэлний тохиргоо хадгалагдлаа.",
    "Ready": "Бэлэн",
    "Opening local database…": "Дотоод өгөгдлийн санг нээж байна…",
    "No transactions loaded": "Гүйлгээ ачаалаагүй байна",
    "Nothing to show yet.": "Харуулах мэдээлэл алга.",
    "Select an account and an XLSX statement to preview.": "Урьдчилан харахын тулд данс болон XLSX хуулга сонгоно уу.",
    "Loading Dashboard…": "Хураангуйг ачаалж байна…",
    "Refreshing Dashboard…": "Хураангуйг шинэчилж байна…",
    "Calculating Dashboard…": "Хураангуйг тооцоолж байна…",
    "Parsing and validating statement…": "Хуулгыг шалгаж байна…",
    "Committing the complete import…": "Импортыг хадгалж байна…",
    "Canceling preview…": "Урьдчилан харахыг цуцалж байна…",
    "Saving account…": "Дансыг хадгалж байна…",
    "Loading transactions…": "Гүйлгээг ачаалж байна…",
    "Creating and validating backup…": "Нөөц үүсгэж шалгаж байна…",
    "Processing review action…": "Ангиллын үйлдлийг боловсруулж байна…",
    "Transactions changed; refreshing Dashboard…": "Гүйлгээ өөрчлөгдлөө; хураангуйг шинэчилж байна…",
    "All time: no transactions. Import a statement or change the date range.": "Гүйлгээ алга. Хуулга импортлох эсвэл хугацааг өөрчилнө үү.",
    "Select one Dashboard row to open its transactions.": "Гүйлгээг харахын тулд хураангуйн нэг мөр сонгоно уу.",
    "Select one transaction to edit.": "Засахын тулд нэг гүйлгээ сонгоно уу.",
    "Select a rule first.": "Эхлээд дүрэм сонгоно уу.",
    "Select an active rule first.": "Эхлээд идэвхтэй дүрэм сонгоно уу.",
    "Refresh to load transactions awaiting review.": "Ангилах гүйлгээг ачаалахын тулд шинэчилнэ үү.",
    "Needs review": "Ангилах шаардлагатай",
    "Manual / protected": "Гараар / хамгаалсан",
    "Excluded": "Хассан",
    "Worksheet 1": "Ажлын хуудас 1",
    "no transactions": "гүйлгээ алга",
    "Mongolian localization and interface settings": "Монгол хэл ба интерфэйсийн тохиргоо",
    "App version": "Програмын хувилбар",
    "Database version": "Өгөгдлийн сангийн хувилбар",
    "Active data location:": "Өгөгдлийн байршил:",
    "Kind": "Төрөл",
    "No category": "Ангилалгүй",
    "Protected": "Хамгаалсан",
    "Unlocked": "Хамгаалалтгүй",
    "At-a-glance totals by currency; net is not an account balance.": "Валют тус бүрийн товч дүн. Цэвэр дүн нь дансны үлдэгдэл биш.",
    "Search, filter, inspect and edit imported transactions.": "Импортолсон гүйлгээг хайх, шүүх, харах, засах.",
    "Preview an XLSX statement and confirm every import decision.": "XLSX хуулгыг шалгаж, импортын шийдвэр бүрийг баталгаажуулах.",
    "Classify unknown transactions deliberately; no category is assigned automatically.": "Танигдаагүй гүйлгээг өөрөө ангилна. Ангиллыг автоматаар оноохгүй.",
    "Manage exact merchant rules for future imports.": "Цаашдын импортод үйлчлэх худалдааны газрын дүрмийг удирдах.",
    "Review income, expenses, net cash flow and unclassified items.": "Орлого, зарлага, цэвэр мөнгөн урсгал болон ангилаагүй гүйлгээг хянах.",
    "Selected transactions only; manual protection will be enabled.": "Зөвхөн сонгосон гүйлгээнд үйлчилнэ; гараар ангилсныг хамгаална.",
    "Also save/enable an exact rule for future imports.": "Цаашдын импортод яг тохирох дүрэм хадгалж/идэвхжүүлнэ.",
    "Select eligible rows to apply. Locked, incompatible and unselected rows will not change.": "Хэрэгжүүлэх мөрүүдийг сонгоно. Хамгаалсан, тохирохгүй болон сонгоогүй мөр өөрчлөгдөхгүй.",
    "Target category:": "Зорилтот ангилал:",
    "Affected candidates:": "Хамаарах боломжит мөрүүд:",
    "Confirm these changes": "Эдгээр өөрчлөлтийг батлах",
    "Apply to selected rows": "Сонгосон мөрөнд хэрэгжүүлэх",
    "Cancel / skip for later": "Цуцлах / дараа үзэх",
    "Preview changes - nothing has been saved": "Өөрчлөлтийг харах — одоогоор хадгалаагүй",
    "Edit transaction - bank source remains unchanged": "Гүйлгээ засах — банкны эх сурвалж өөрчлөгдөхгүй",
    "Effective values": "Одоогийн утгууд",
    "Bank source (read-only)": "Банкны эх сурвалж (зөвхөн унших)",
    "Edit history (read-only)": "Засварын түүх (зөвхөн унших)",
    "ISO date / time": "ISO огноо / цаг",
    "Merchant display (does not change matching key)": "Худалдааны газрын нэр (тохируулах түлхүүр өөрчлөгдөхгүй)",
    "Note": "Тэмдэглэл",
    "Explicitly clear manual protection (allow later rule application)": "Гараар хамгаалсныг цуцлах (дараа нь дүрэм хэрэгжүүлэхийг зөвшөөрөх)",
    "Current protection:": "Одоогийн хамгаалалт:",
    "Save this transaction only": "Зөвхөн энэ гүйлгээг хадгалах",
    "No edits recorded.": "Засварын түүх байхгүй.",
    "Choose a Khan Bank MNT statement": "Хаан Банкны MNT хуулга сонгох",
    "Choose a local backup folder": "Дотоод нөөцлөх хавтас сонгох",
    "Choose a Personal Finance backup": "Хувийн санхүүгийн нөөц файл сонгох",
    "Export all transactions matching applied filters": "Хэрэгжүүлсэн шүүлтүүрт тохирох бүх гүйлгээг экспортлох",
    "Account name": "Дансны нэр",
    "IBAN exactly as shown on the statement (text)": "Хуулгад харагдаж буй IBAN (яг хэвээр нь)",
    "Save account": "Данс хадгалах",
    "Preview validated. Click Commit import to save these transactions.": "Урьдчилан шалгалаа. Эдгээр гүйлгээг хадгалахын тулд импортыг баталгаажуулна уу.",
    "An interface action failed. Refresh the view or close and reopen the app.": "Интерфэйсийн үйлдэл амжилтгүй боллоо. Дэлгэцийг шинэчлэх эсвэл програмыг хааж дахин нээнэ үү.",
    "Refresh the Dashboard and select a category row.": "Хураангуйг шинэчлээд ангиллын мөр сонгоно уу.",
    "Refresh the Dashboard and select a monthly row.": "Хураангуйг шинэчлээд сарын мөр сонгоно уу.",
    "The start date must not be after the end date.": "Эхлэх огноо дуусах огнооноос хойш байж болохгүй.",
    "Enter valid dates as YYYY-MM-DD, or leave them blank.": "Огноог YYYY-MM-DD хэлбэрээр оруулах эсвэл хоосон үлдээнэ үү.",
    "Add Khan Bank account": "Хаан Банкны данс нэмэх",
    "Khan Bank · MNT\nSaving creates an account only; no transactions are imported.": "Хаан Банк · MNT\nЗөвхөн данс хадгална; гүйлгээ импортлохгүй.",
    "Date / direction": "Огноо / чиглэл",
    "Valid": "Хүчинтэй",
    "Invalid": "Хүчингүй",
    "Duplicate": "Давхардсан",
    "Ambiguous": "Тодорхойгүй",
    "Choose": "Сонгох",
    "keep": "хадгалах",
    "skip": "алгасах",
    "Incoming": "Импортлох",
    "Individual item (no group)": "Тусдаа гүйлгээ (бүлэггүй)",
    "This replaces the saved rule for this scope.": "Энэ хүрээнд хадгалсан дүрмийг солино.",
    "Target category": "Зорилтот ангилал",
    "Apply or cancel the current preview before editing.": "Засахаас өмнө одоогийн урьдчилсан харалтыг хэрэгжүүлэх эсвэл цуцална уу.",
    "Enter an account name and its statement IBAN.": "Дансны нэр болон хуулгад буй IBAN-ыг оруулна уу.",
    "No transactions match the applied filters. No export file was created.": "Хэрэгжүүлсэн шүүлтүүрт гүйлгээ тохирсонгүй. Файл үүсгээгүй.",
    "Account saved. Select a statement and confirm its account before previewing.": "Данс хадгалагдлаа. Урьдчилан харахаас өмнө хуулга сонгож, дансаа баталгаажуулна уу.",
    "Preview canceled. No transactions or import metadata were changed.": "Урьдчилан харалтыг цуцаллаа. Гүйлгээ болон импортын мэдээлэл өөрчлөгдөөгүй.",
    "Preview validated. Choose Keep/Skip for ambiguous rows, then click Commit import.": "Урьдчилан шалгалаа. Тодорхойгүй мөр бүрийг хадгалах/алгасах сонгоод импортыг баталгаажуулна уу.",
    "Import blocked: the statement account/currency does not match the selected account. Cancel preview, select or add the matching account, confirm it, and preview again. Valid row counts do not mean the statement can be committed.": "Импорт хориглогдлоо: хуулгын данс/валют сонгосон данстай таарахгүй байна. Урьдчилан харалтыг цуцалж, тохирох данс сонгох эсвэл нэмээд баталгаажуулан дахин шалгана уу. Хүчинтэй мөр байгаа нь хуулгыг хадгалж болно гэсэн үг биш.",
    "Import blocked. Review errors, cancel, and resolve the source problem before creating a new preview.": "Импорт хориглогдлоо. Алдааг шалгаж урьдчилан харалтыг цуцлаад эх сурвалжийн асуудлыг зассаны дараа дахин шалгана уу.",
    "Preview canceled. No categories or rules were changed.": "Урьдчилан харалтыг цуцаллаа. Ангилал болон дүрэм өөрчлөгдөөгүй.",
    "Selected transactions classified and protected.": "Сонгосон гүйлгээг ангилж хамгааллаа.",
    "Rule applied only to explicitly selected eligible rows.": "Дүрмийг зөвхөн ил тод сонгосон тохирох мөрүүдэд хэрэгжүүллээ.",
    "Rule saved for future use; past classifications unchanged.": "Дүрмийг цаашид ашиглахаар хадгаллаа; өмнөх ангилал өөрчлөгдөөгүй.",
    "Transaction correction saved with history; bank source unchanged.": "Гүйлгээний засварыг түүхтэй нь хадгаллаа; банкны эх сурвалж өөрчлөгдөөгүй.",
    "Restore canceled. The current database is unchanged.": "Сэргээхийг цуцаллаа. Одоогийн өгөгдлийн сан өөрчлөгдөөгүй.",
    "Restore complete. Close and reopen the app.": "Сэргээж дууслаа. Програмыг хааж дахин нээнэ үү.",
    "Closing after the current operation finishes…": "Одоогийн үйлдэл дууссаны дараа хаана…",
    "Transactions awaiting review. Use Review to classify or edit selected rows.": "Ангилах гүйлгээнүүд. Сонгосон мөрийг ангилах эсвэл засахын тулд ангиллын хэсгийг нээнэ үү.",
    "Dashboard selection: date and currency filters are applied.": "Хураангуйгаас сонгосон: огноо болон валютын шүүлтүүр хэрэгжлээ.",
    "The database worker is unavailable. Close and reopen the app.": "Өгөгдлийн сангийн ажиллагаа боломжгүй байна. Програмыг хааж дахин нээнэ үү.",
    "Confirm restore": "Сэргээхийг баталгаажуулах",
    "Restore complete": "Сэргээж дууслаа",
    "Your current app language is saved locally.": "Програмын хэлний тохиргоо энэ төхөөрөмжид хадгалагдана.",
    "Create a validated local database backup.": "Дотоод өгөгдлийн сангийн баталгаажсан нөөц үүсгэнэ.",
    "Preview and confirm a backup restore; current data is protected by a safety backup.": "Нөөцийг шалгаж сэргээхийг батална; эхлээд одоогийн өгөгдлийг аюулгүй нөөцөлнө.",
    "Export all transactions matching the applied filters.": "Хэрэгжүүлсэн шүүлтүүрт тохирох бүх гүйлгээг экспортлоно.",
    "View app version, data location and workflow guidance.": "Програмын хувилбар, өгөгдлийн байршил болон зааврыг харуулна.",
    "Open the active local data directory.": "Идэвхтэй дотоод өгөгдлийн хавтсыг нээнэ.",
    "Choose Mongolian or English for the interface.": "Интерфэйсийн Монгол эсвэл Англи хэлийг сонгоно.",
    "Check the statement before writing any transactions.": "Гүйлгээ хадгалахаас өмнө хуулгыг шалгана.",
    "Save the validated import after all required decisions are complete.": "Шаардлагатай шийдвэрийг бүрэн гаргасны дараа шалгасан импортыг хадгална.",
    "Discard this preview without importing transactions.": "Гүйлгээ импортлохгүйгээр урьдчилан харалтыг цуцална.",
    "Apply the selected transaction filters.": "Сонгосон гүйлгээний шүүлтүүрийг хэрэгжүүлнэ.",
    "Edit one selected transaction; original bank values remain unchanged.": "Сонгосон нэг гүйлгээг засна; банкны эх утгууд өөрчлөгдөхгүй.",
    "Open the queue of transactions that need classification.": "Ангилах шаардлагатай гүйлгээнүүдийн жагсаалтыг нээнэ.",
    "Reload transactions awaiting classification.": "Ангилах шаардлагатай гүйлгээнүүдийг дахин ачаална.",
    "Review selected rows before changing their category.": "Ангиллыг өөрчлөхөөс өмнө сонгосон мөрүүдийг шалгана.",
    "Stop this exact rule from affecting future imports.": "Энэ дүрмийг цаашдын импортод үйлчлэхийг зогсооно.",
    "Save the interface language locally; restart to apply it.": "Интерфэйсийн хэлийг төхөөрөмжид хадгална; хэрэгжүүлэхийн тулд дахин эхлүүлнэ.",
    "% of this currency/kind": "Валют/төрлийн хувь",
    "Source": "Эх сурвалж",
    "Date": "Огноо",
    "Choose a language": "Хэл сонгох",
    "Current protection: protected. Saving protects this edit by default.\nA direction change needs a compatible kind/category, or choose unclassified and No category.": "Одоогийн хамгаалалт: хамгаалсан. Хадгалахад энэ засвар хамгаалагдана.\nЧиглэл өөрчлөхөд тохирох төрөл/ангилал сонгох эсвэл ангилаагүй, ангилалгүйг сонгоно уу.",
    "Current protection: unlocked. Saving protects this edit by default.\nA direction change needs a compatible kind/category, or choose unclassified and No category.": "Одоогийн хамгаалалт: хамгаалалтгүй. Хадгалахад энэ засвар хамгаалагдана.\nЧиглэл өөрчлөхөд тохирох төрөл/ангилал сонгох эсвэл ангилаагүй, ангилалгүйг сонгоно уу.",
    "Data folder:": "Өгөгдлийн хавтас:",
    "Import and classification must share the same repository.": "Импорт болон ангилал ижил санг ашиглах ёстой.",
    "Enter both custom dates as valid YYYY-MM-DD values.": "Хоёр огноог хоёуланг YYYY-MM-DD хэлбэрээр зөв оруулна уу.",
    "Direction / kind": "Чиглэл / төрөл",
    "No chart data for the selected period and currency.": "Сонгосон хугацаа болон валютад графикийн өгөгдөл алга.",
    "Excluded": "Хассан",
    "Chart category kind must be income or expense.": "Графикийн ангиллын төрөл орлого эсвэл зарлага байх ёстой.",
    "Save selected changes": "Сонгосон өөрчлөлтийг хадгалах",
    "Assign the selected category to the selected transactions.": "Сонгосон гүйлгээнд сонгосон ангиллыг онооно.",
    "Skipped for later. No data changed; unreviewed items remain available after restart.": (
        "Дараа үзэхээр орхилоо. Өгөгдөл өөрчлөгдөөгүй; ангилаагүй гүйлгээнүүд дахин нээхэд хэвээр байна."),
    "Choose a category.": "Ангилал сонгоно уу.",
    "Choose a category compatible with every selected transaction's direction.": (
        "Сонгосон бүх гүйлгээний чиглэлд тохирох ангилал сонгоно уу."),
    "Apply or cancel the current review preview first.": (
        "Эхлээд одоогийн ангиллын урьдчилсан харалтыг хэрэгжүүлэх эсвэл цуцална уу."),
    "Select distinct transactions to preview.": "Ангилах гүйлгээгээ сонгоно уу.",
    "Review items changed; refresh and select again.": "Ангилах жагсаалт өөрчлөгдсөн байна; шинэчлээд дахин сонгоно уу.",
    "A future rule requires one reliable, unlocked merchant group and direction.": (
        "Цаашдын дүрэм хадгалахад нэг тодорхой, хамгаалалтгүй худалдааны газрын бүлэг болон чиглэл шаардлагатай."),
    "Create a new assignment preview.": "Шинээр урьдчилсан харалт үүсгэнэ үү.",
    "Selected transactions changed; cancel and preview again.": (
        "Сонгосон гүйлгээ өөрчлөгдсөн байна; цуцлаад дахин шалгана уу."),
    "The merchant rule changed; cancel and preview again.": (
        "Худалдааны газрын дүрэм өөрчлөгдсөн байна; цуцлаад дахин шалгана уу."),
    "Create a new rule preview.": "Дүрмийн урьдчилсан харалтыг шинээр үүсгэнэ үү.",
    "Select the eligible rows to apply; no rows are selected by default.": (
        "Хэрэгжүүлэх тохирох мөрүүдийг сонгоно уу; анхдагчаар мөр сонгогдоогүй."),
    "The rule changed; refresh before editing it.": "Дүрэм өөрчлөгдсөн байна; засахаас өмнө шинэчилнэ үү.",
}

TOOLTIPS = {
    "Backup…": "Create a validated local database backup.",
    "Restore…": "Preview and confirm a backup restore; current data is protected by a safety backup.",
    "Export CSV…": "Export all transactions matching the applied filters.",
    "Help / About": "View app version, data location and workflow guidance.",
    "Open data folder": "Open the active local data directory.",
    "Settings": "Choose Mongolian or English for the interface.",
    "Preview import": "Check the statement before writing any transactions.",
    "Commit import": "Save the validated import after all required decisions are complete.",
    "Cancel preview": "Discard this preview without importing transactions.",
    "Apply / refresh": "Apply the selected transaction filters.",
    "Edit selected": "Edit one selected transaction; original bank values remain unchanged.",
    "Review unknown merchants": "Open the queue of transactions that need classification.",
    "Refresh review": "Reload transactions awaiting classification.",
    "Save selected changes": "Assign the selected category to the selected transactions.",
    "Preview selected changes": "Review selected rows before changing their category.",
    "Disable rule": "Stop this exact rule from affecting future imports.",
    "Save language": "Save the interface language locally; restart to apply it.",
    "Dashboard": "View totals separately for each currency.",
    "Transactions": "Search and manage individual transactions.",
    "Import statement": "Preview and import a bank statement.",
    "Review": "Classify unknown transactions; assignments are explicit.",
    "Rules": "Manage rules that apply to future imports.",
}

MESSAGE_TEMPLATES = {
    "{count} mapping rules loaded.": "{count} зураглалын дүрэм ачааллаа.",
    "Valid: {valid} · Invalid: {invalid} · Duplicate: {duplicate} · Ambiguous: {ambiguous} · Blocking errors: {blockers}. Nothing has been imported yet.": (
        "Хүчинтэй: {valid} · Хүчингүй: {invalid} · Давхардсан: {duplicate} · "
        "Тодорхойгүй: {ambiguous} · Блоклосон алдаа: {blockers}. Одоогоор импорт хийгдээгүй."
    ),
    "Ready": "Бэлэн",
    "Loading Dashboard…": "Хураангуйг ачаалж байна…",
    "Refreshing Dashboard…": "Хураангуйг шинэчилж байна…",
    "All time": "Бүх хугацаа",
    "{period}: no transactions. Import a statement or change the date range.": "{period}: гүйлгээ алга. Хуулга импортлох эсвэл хугацааг өөрчилнө үү.",
    "{period}: {count} transactions; {unclassified} unclassified. Unclassified, transfer and excluded amounts are omitted from income/expense/net totals. Net is not an account balance.": (
        "{period}: {count} гүйлгээ; {unclassified} ангилаагүй. Ангилаагүй, шилжүүлсэн болон хассан дүн орлого/зарлага/цэвэр дүнд орохгүй. Цэвэр дүн нь дансны үлдэгдэл биш."
    ),
    "Page {page} of {pages} · {count} rows": "{pages} хуудасны {page} · {count} мөр",
    "Page {page} of {pages} · {count} transactions": "{pages} хуудасны {page} · {count} гүйлгээ",
    "{period} through {end} (inclusive)": "{period}–{end} (дуусах өдрийг багтаана)",
    "{groups} merchant groups; {individual} individual items. Skipping changes nothing.": "{groups} худалдааны газрын бүлэг; {individual} тусдаа гүйлгээ. Алгасахад өгөгдөл өөрчлөгдөхгүй.",
    "{count} transactions selected for review.": "Ангилахаар {count} гүйлгээ сонгогдлоо.",
    "Duplicate decisions: {selected} of {total}. Each skipped occurrence must have its own existing match.": "Давхардлын шийдвэр: {total}-аас {selected}. Алгасах бүрт тусдаа тохирох өмнөх гүйлгээ сонгоно.",
    "Validated database v{schema}: {transactions} transactions, {accounts} accounts, {rules} rules.\n\nReplace the current database with this snapshot?\nA validated safety backup will be saved in the active data folder's backups subfolder first.\nClose other app instances. After success, close and reopen this app.\nThe selected backup is kept. Cancel leaves current data unchanged.": (
        "Өгөгдлийн сан v{schema} шалгагдлаа: {transactions} гүйлгээ, {accounts} данс, {rules} дүрэм.\n\n"
        "Одоогийн өгөгдлийн санг энэ нөөцөөр солих уу?\n"
        "Эхлээд идэвхтэй өгөгдлийн хавтасны backups дэд хавтсанд аюулгүй нөөц үүсгэнэ.\n"
        "Бусад програмын цонхыг хаана уу. Амжилттай болсны дараа програмыг хааж дахин нээнэ.\n"
        "Сонгосон нөөц файлыг хадгална. Цуцлахад одоогийн өгөгдөл өөрчлөгдөхгүй."
    ),
    "Restore completed. Close and reopen the app. Safety backup: {path}": "Сэргээж дууслаа. Програмыг хааж дахин нээнэ үү. Аюулгүй нөөц: {path}",
    "Exported {count} transactions to: {path}": "{count} гүйлгээг экспортоллоо: {path}",
    "Backup completed and validated: {path}": "Нөөц үүсгэж шалгалаа: {path}",
    "Backup completed and validated:": "Нөөц үүсгэж шалгалаа:",
    "App {version} | Database schema {schema}\nData folder: {folder}\n\nOffline; no account, cloud or API key.\nImport: select account/file, preview, then confirm.\nReview: selected-only categories by default; rules are optional.\nTransactions: Apply filters before Export CSV (all matching pages).\nBackup saves a validated snapshot. Restore requires confirmation,\ncreates a safety backup, and requires close/reopen afterward.\nClose other app instances before restore.\nFull instructions: docs/user_guide.md in the project folder.": (
        "Програм {version} | Өгөгдлийн сангийн хувилбар {schema}\nӨгөгдлийн хавтас: {folder}\n\n"
        "Интернэт, бүртгэл, үүлэн үйлчилгээ болон API түлхүүр шаардлагагүй.\n"
        "Импорт: данс/файл сонгоод шалгаж баталгаажуулна.\n"
        "Ангилал: зөвхөн сонгосон гүйлгээнд үйлчилнэ; дүрэм сонголтоор хадгална.\n"
        "Гүйлгээ: CSV гаргахаас өмнө шүүлтүүрээ хэрэгжүүлнэ (тохирох бүх хуудсыг экспортлоно).\n"
        "Нөөцлөлтийг шалгаж хадгална. Сэргээхэд баталгаа шаардлагатай бөгөөд\n"
        "эхлээд аюулгүйн нөөц үүсгэнэ. Дараа нь програмыг хааж дахин нээнэ.\n"
        "Сэргээхийн өмнө бусад програмын цонхыг хаана уу.\n"
        "Дэлгэрэнгүй: төслийн docs/user_guide.md."
    ),
}

_active_language = DEFAULT_LANGUAGE
_COMBO_LABELS = {
    "All directions", "Debit", "Credit", "Zero",
    "All time", "This month", "Last month", "This year", "Custom range",
    "Any bank", "Any account", "Any direction", "All rules", "Active", "Disabled", "Light mode", "Dark mode", "All months", "All currencies", "Archived", "All",
    "pos_id", "merchant", "description", "exact", "contains", "starts_with", "ends_with", "regex",
}


def set_language(language: str) -> None:
    global _active_language
    if language not in LANGUAGE_NAMES:
        raise ValueError(f"Unsupported language: {language}")
    _active_language = language


def get_language() -> str:
    return _active_language


def translate(message: str, language: str | None = None) -> str:
    selected = language or _active_language
    if selected == "mn":
        if message in TRANSLATIONS:
            return TRANSLATIONS[message]
        if message in TRANSLATIONS_EN:
            return message
        for sep in ("  ", " "):
            if sep in message:
                prefix, remainder = message.split(sep, 1)
                if remainder in TRANSLATIONS:
                    return f"{prefix}{sep}{TRANSLATIONS[remainder]}"
        return TRANSLATIONS.get(message, message)
    if selected == "en":
        if message in TRANSLATIONS_EN:
            return TRANSLATIONS_EN[message]
        for sep in ("  ", " "):
            if sep in message:
                prefix, remainder = message.split(sep, 1)
                if remainder in TRANSLATIONS_EN:
                    return f"{prefix}{sep}{TRANSLATIONS_EN[remainder]}"
        return message
    raise ValueError(f"Unsupported language: {selected}")


def translate_format(template: str, /, **values) -> str:
    selected = _active_language
    localized = MESSAGE_TEMPLATES.get(template, template) if selected == "mn" else template
    return localized.format(**values)


def source_text(display_text: str, choices=None) -> str:
    """Return the English source label for translated combo-box values."""
    if _active_language == "en":
        return display_text
    reverse = {TRANSLATIONS.get(english, english): english for english in choices} if choices else {
        localized: english for english, localized in TRANSLATIONS.items()}
    return reverse.get(display_text, display_text)


def _read_settings(data_dir: Path) -> dict:
    path = Path(data_dir) / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass
    return {}


def _write_settings(data_dir: Path, settings: dict) -> None:
    folder = Path(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=folder, delete=False, suffix=".tmp") as stream:
            temporary_path = Path(stream.name)
            json.dump(settings, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, folder / "settings.json")
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def load_theme(data_dir: Path) -> str:
    """Load the UI theme preference; absent settings use dark mode."""
    path = Path(data_dir) / "settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_THEME
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read theme settings: {error}") from error
    theme = settings.get("theme") if isinstance(settings, dict) else None
    if theme is None:
        return DEFAULT_THEME
    if theme not in THEME_NAMES:
        raise ValueError("Theme settings must contain 'dark' or 'light'.")
    return theme


def save_theme(data_dir: Path, theme: str) -> None:
    if theme not in THEME_NAMES:
        raise ValueError(f"Unsupported theme: {theme}")
    settings = _read_settings(data_dir)
    settings["theme"] = theme
    _write_settings(data_dir, settings)


def load_language(data_dir: Path) -> str:
    """Load the UI-only preference; absent settings use Mongolian."""
    path = Path(data_dir) / "settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_LANGUAGE
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read language settings: {error}") from error
    language = settings.get("language") if isinstance(settings, dict) else None
    if language is None:
        return DEFAULT_LANGUAGE
    if language not in LANGUAGE_NAMES:
        raise ValueError("Language settings must contain 'mn' or 'en'.")
    return language


def save_language(data_dir: Path, language: str) -> None:
    if language not in LANGUAGE_NAMES:
        raise ValueError(f"Unsupported language: {language}")
    settings = _read_settings(data_dir)
    settings["language"] = language
    _write_settings(data_dir, settings)


def load_category_settings(data_dir: Path) -> dict:
    settings = _read_settings(data_dir)
    disabled = set(settings.get("disabled_categories", []))
    names = {int(k) if str(k).isdigit() else k: str(v)
             for k, v in settings.get("category_display_names", {}).items()}
    return {"disabled_ids": disabled, "display_names": names}


def save_category_settings(data_dir: Path, disabled_ids, display_names) -> None:
    settings = _read_settings(data_dir)
    settings["disabled_categories"] = sorted(int(i) for i in disabled_ids)
    settings["category_display_names"] = {str(k): str(v) for k, v in display_names.items() if str(v).strip()}
    _write_settings(data_dir, settings)


def get_category_display_name(category: dict | int | str | None, categories: list[dict] | None = None,
                              language: str | None = None, custom_names: dict | None = None) -> str:
    if category is None:
        return "—"
    cat_id, raw_name = None, None
    if isinstance(category, dict):
        cat_id = category.get("id")
        raw_name = category.get("name")
    elif isinstance(category, int):
        cat_id = category
        if categories:
            matched = next((c for c in categories if c.get("id") == cat_id), None)
            raw_name = matched.get("name") if matched else None
    elif isinstance(category, str):
        raw_name = category
        if categories:
            matched = next((c for c in categories if c.get("name") == raw_name), None)
            cat_id = matched.get("id") if matched else None
    if custom_names and cat_id is not None and cat_id in custom_names:
        return custom_names[cat_id]
    if raw_name:
        return translate(raw_name, language)
    return "—"


def resolve_category_by_display_name(display_text: str, categories: list[dict],
                                    language: str | None = None, custom_names: dict | None = None) -> dict | None:
    raw = (display_text or "").strip()
    if not raw or raw in ("All categories", "Бүх ангилал", "No category", "Ангилалгүй", "—"):
        return None
    # 1. Custom display name match
    if custom_names:
        for cid, custom in custom_names.items():
            if custom.strip().lower() == raw.lower():
                matched = next((c for c in categories if c.get("id") == cid), None)
                if matched:
                    return matched
    # 2. Display name match
    for c in categories:
        disp = get_category_display_name(c, categories, language, custom_names)
        if disp.strip().lower() == raw.lower():
            return c
    # 3. Exact raw canonical name match
    for c in categories:
        name = str(c.get("name", "")).strip()
        if name.lower() == raw.lower():
            return c
    # 4. Cross-language translations match
    for c in categories:
        name = str(c.get("name", "")).strip()
        if translate(name, "mn").strip().lower() == raw.lower():
            return c
        if translate(name, "en").strip().lower() == raw.lower():
            return c
    return None


def localize_widget_tree(root) -> None:
    """Translate static widget labels/headings and choice labels in-place."""
    _localize_child(root)


def _localize_child(widget) -> None:
    try:
        text = widget.cget("text")
        if text:
            original_text = str(text)
            widget.configure(text=translate(str(text)))
            if widget.winfo_class() == "TButton" and original_text in TOOLTIPS:
                ToolTip(widget, translate(TOOLTIPS[original_text]))
    except (AttributeError, TypeError, tkinter.TclError):
        pass
    if widget.winfo_class() == "Treeview":
        for column in widget["columns"]:
            heading = widget.heading(column, "text")
            if heading:
                widget.heading(column, text=translate(str(heading)))
    if widget.winfo_class() == "TNotebook":
        for tab in widget.tabs():
            label = widget.tab(tab, "text")
            if label:
                widget.tab(tab, text=translate(str(label)))
    if widget.winfo_class() == "TCombobox":
        values = widget.cget("values")
        if values:
            widget.configure(values=tuple(
                translate(str(value)) if str(value) in _COMBO_LABELS else value
                for value in values))
    children = widget.winfo_children()
    if not isinstance(children, (tuple, list)):
        return
    for child in children:
        _localize_child(child)


class ToolTip:
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.pending = None
        self.window = None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def schedule(self, _event=None):
        self.pending = self.widget.after(550, self.show)

    def show(self):
        self.pending = None
        if self.window is not None or not self.widget.winfo_exists():
            return
        self.window = tkinter.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{self.widget.winfo_rootx() + 12}+{self.widget.winfo_rooty() + self.widget.winfo_height() + 5}")
        tip_bg, tip_fg = "#252e3d", "#f1f5f9"
        try:
            from app.ui.theme import get_current_theme
            tokens = get_current_theme()
            tip_bg = "#252e3d" if tokens.name == "dark" else "#fff8dc"
            tip_fg = "#f1f5f9" if tokens.name == "dark" else "#000000"
        except Exception:
            pass
        tkinter.Label(self.window, text=self.text, background=tip_bg, foreground=tip_fg,
                      relief="solid", borderwidth=1, padx=7, pady=4, wraplength=320).pack()

    def hide(self, _event=None):
        if self.pending is not None:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.window is not None:
            self.window.destroy()
            self.window = None
