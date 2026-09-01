import React from "../react-shim.js";

/**
 * Responsive data table: renders as a normal table on wide viewports and
 * collapses into stacked label/value "cards" per row on narrow viewports
 * (see .data-table rules in admin.css) using the `data-label` attributes
 * below — no separate mobile markup needed.
 */
export function DataTable({
  columns,
  rows,
  getRowId,
  selectable = false,
  selectedIds,
  onToggleRow,
  onToggleAll,
  renderActions,
  caption,
  testId,
}) {
  const allSelected = selectable && rows.length > 0 && rows.every((row) => selectedIds?.has(getRowId(row)));
  return (
    <div className="table-wrap" data-testid={testId}>
      <table className="data-table">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {selectable ? (
              <th scope="col" className="table-select-col">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={() => onToggleAll(!allSelected)}
                  aria-label="Вибрати всі рядки на сторінці"
                  data-testid={testId ? `${testId}-select-all` : undefined}
                />
              </th>
            ) : null}
            {columns.map((col) => (
              <th key={col.key} scope="col">
                {col.header}
              </th>
            ))}
            {renderActions ? (
              <th scope="col">
                <span className="sr-only">Дії</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const id = getRowId(row);
            return (
              <tr key={id} data-testid={testId ? `${testId}-row-${id}` : undefined}>
                {selectable ? (
                  <td data-label="Вибір" className="table-select-col">
                    <input
                      type="checkbox"
                      checked={selectedIds?.has(id) ?? false}
                      onChange={() => onToggleRow(id)}
                      aria-label={`Вибрати рядок ${id}`}
                      data-testid={testId ? `${testId}-select-${id}` : undefined}
                    />
                  </td>
                ) : null}
                {columns.map((col) => (
                  <td key={col.key} data-label={col.header}>
                    {col.render ? col.render(row) : row[col.key]}
                  </td>
                ))}
                {renderActions ? (
                  <td className="table-actions" data-label="Дії">
                    {renderActions(row)}
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
