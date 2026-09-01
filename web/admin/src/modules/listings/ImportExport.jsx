import React, { useRef, useState } from "../../react-shim.js";
import { api, downloadFile } from "../../lib/apiClient.js";
import { useToast } from "../../components/Toast.jsx";
import { Icon } from "../../components/icons.jsx";
import { Card } from "../../components/Layout.jsx";
import { buildCsvTemplate, parseCsvPreview } from "./csvUtils.js";

export function ImportExport({ onImported }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [importing, setImporting] = useState(false);
  const [importErrors, setImportErrors] = useState(null);
  const [exportStatus, setExportStatus] = useState("");
  const [exportCity, setExportCity] = useState("");
  const inputRef = useRef(null);
  const toast = useToast();

  function handleFileChange(event) {
    const selected = event.target.files?.[0] || null;
    setFile(selected);
    setImportErrors(null);
    setPreview(null);
    if (!selected) return;
    selected.text().then((text) => setPreview(parseCsvPreview(text, 8)));
  }

  async function handleImport() {
    if (!file) return;
    setImporting(true);
    setImportErrors(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const result = await api.upload("/import/csv", formData);
      toast.success(`Імпортовано оголошень: ${result.imported}`);
      setFile(null);
      setPreview(null);
      if (inputRef.current) inputRef.current.value = "";
      onImported?.();
    } catch (err) {
      if (err.status === 422 && err.payload?.details) {
        setImportErrors(err.payload.details);
      } else {
        toast.error(err.message);
      }
    } finally {
      setImporting(false);
    }
  }

  function handleDownloadTemplate() {
    const blob = new Blob([buildCsvTemplate()], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "ua-homes-listings-template.csv";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function handleExport() {
    const query = {};
    if (exportStatus) query.status = exportStatus;
    if (exportCity.trim()) query.city = exportCity.trim();
    downloadFile("/export/csv", query);
  }

  return (
    <div className="import-export-grid">
      <Card title="Імпорт з CSV" description="Заголовки: title, city, district, price, rooms, area (обов'язкові) та інші">
        <div className="import-controls">
          <button type="button" className="btn btn-secondary" onClick={handleDownloadTemplate}>
            <Icon name="download" size={15} />
            Завантажити шаблон
          </button>
          <label className="btn btn-secondary" htmlFor="csv-import-input">
            <Icon name="upload" size={15} />
            Обрати файл CSV
          </label>
          <input
            ref={inputRef}
            id="csv-import-input"
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            onChange={handleFileChange}
          />
          {file ? <span className="import-filename">{file.name}</span> : null}
        </div>

        {preview ? (
          <div className="table-wrap csv-preview">
            <table className="data-table">
              <thead>
                <tr>
                  {preview[0]?.map((cell, index) => (
                    <th key={index} scope="col">
                      {cell}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.slice(1).map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((cell, cellIndex) => (
                      <td key={cellIndex} data-label={preview[0]?.[cellIndex]}>
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="import-preview-note">Попередній перегляд перших рядків. Валідація виконується на сервері.</p>
          </div>
        ) : null}

        {importErrors ? (
          <div className="import-errors" role="alert">
            <p>Помилки імпорту (зміни скасовано):</p>
            <ul>
              {importErrors.map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="form-actions">
          <button type="button" className="btn btn-primary" onClick={handleImport} disabled={!file || importing}>
            {importing ? "Імпортування…" : "Імпортувати"}
          </button>
        </div>
      </Card>

      <Card title="Експорт у CSV" description="Завантажте поточну базу оголошень із фільтрами">
        <div className="export-controls">
          <label className="form-field">
            <span className="form-label">Статус</span>
            <select value={exportStatus} onChange={(e) => setExportStatus(e.target.value)}>
              <option value="">Усі статуси</option>
              <option value="draft">Чернетка</option>
              <option value="published">Опубліковано</option>
              <option value="pending">На розгляді</option>
              <option value="rejected">Відхилено</option>
              <option value="archived">Архів</option>
            </select>
          </label>
          <label className="form-field">
            <span className="form-label">Місто</span>
            <input type="text" value={exportCity} onChange={(e) => setExportCity(e.target.value)} placeholder="Наприклад, Київ" />
          </label>
        </div>
        <div className="form-actions">
          <button type="button" className="btn btn-primary" onClick={handleExport}>
            <Icon name="download" size={15} />
            Експортувати CSV
          </button>
        </div>
      </Card>
    </div>
  );
}
