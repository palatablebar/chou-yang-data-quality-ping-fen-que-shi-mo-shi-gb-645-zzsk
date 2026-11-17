/* 表格排序：点击表头或按回车切换升降序，数字列按数值比较。 */
(function () {
  "use strict";

  const collator = new Intl.Collator("zh-Hans-CN", { numeric: true, sensitivity: "base" });

  function cellText(row, index) {
    const cell = row.children[index];
    return cell ? cell.textContent.trim() : "";
  }

  function numeric(values) {
    return values.every(function (value) {
      return value !== "" && value !== "—" && !Number.isNaN(Number(value.replace(/,/g, "")));
    });
  }

  function sortTable(table, index, ascending) {
    const body = table.tBodies[0];
    if (!body) return;
    const rows = Array.prototype.slice.call(body.rows);
    const values = rows.map(function (row) { return cellText(row, index); });
    const asNumber = numeric(values);
    rows.sort(function (left, right) {
      const a = cellText(left, index);
      const b = cellText(right, index);
      let result;
      if (asNumber) {
        result = Number(a.replace(/,/g, "")) - Number(b.replace(/,/g, ""));
      } else {
        result = collator.compare(a, b);
      }
      return ascending ? result : -result;
    });
    rows.forEach(function (row) { body.appendChild(row); });
  }

  function prepare(table) {
    const headRow = table.tHead ? table.tHead.rows[0] : null;
    if (!headRow) return;
    Array.prototype.forEach.call(headRow.cells, function (th, index) {
      th.setAttribute("data-sort", "1");
      th.setAttribute("tabindex", "0");
      th.setAttribute("role", "columnheader");
      const toggle = function () {
        const current = th.getAttribute("aria-sort");
        const ascending = current !== "ascending";
        Array.prototype.forEach.call(headRow.cells, function (other) {
          other.removeAttribute("aria-sort");
        });
        th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
        sortTable(table, index, ascending);
      };
      th.addEventListener("click", toggle);
      th.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggle();
        }
      });
    });
  }

  function boot() {
    document.querySelectorAll("table[data-sortable]").forEach(prepare);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
