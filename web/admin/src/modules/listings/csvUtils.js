// Minimal CSV tokenizer used only for the client-side import preview (the
// authoritative parse happens server-side in admin_import_csv). Handles
// quoted fields with embedded commas/newlines/escaped quotes.
export function parseCsvPreview(text, maxRows = 10) {
  const rows = [];
  let field = "";
  let row = [];
  let inQuotes = false;
  let i = 0;
  while (i < text.length && rows.length <= maxRows) {
    const char = text[i];
    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i += 1;
        continue;
      }
      field += char;
      i += 1;
      continue;
    }
    if (char === '"') {
      inQuotes = true;
      i += 1;
      continue;
    }
    if (char === ",") {
      row.push(field);
      field = "";
      i += 1;
      continue;
    }
    if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      i += 1;
      continue;
    }
    field += char;
    i += 1;
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((r) => r.some((cell) => cell !== "")).slice(0, maxRows + 1);
}

export const CSV_TEMPLATE_HEADER = [
  "title",
  "city",
  "district",
  "price",
  "rooms",
  "area",
  "floor",
  "total_floors",
  "year_built",
  "property_type",
  "condition_type",
  "status",
  "e_oselya",
  "description",
  "latitude",
  "longitude",
  "images",
];

export function buildCsvTemplate() {
  const sampleRow = [
    "Затишна 2-кімнатна квартира",
    "Київ",
    "Печерський",
    "125000",
    "2",
    "68",
    "5",
    "9",
    "2015",
    "квартира",
    "вторинка",
    "draft",
    "1",
    "Світла квартира з ремонтом",
    "50.4501",
    "30.5234",
    "",
  ];
  return `${CSV_TEMPLATE_HEADER.join(",")}\n${sampleRow.join(",")}\n`;
}
