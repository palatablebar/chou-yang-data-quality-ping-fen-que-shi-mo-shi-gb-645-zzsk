/* 柱图增强：读服务端算好的百分比，补无障碍标签并做一次 150ms 内的入场。 */
(function () {
  "use strict";

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function paintBars(root) {
    root.querySelectorAll(".bar").forEach(function (bar) {
      const fill = bar.querySelector(".bar__fill");
      const label = bar.querySelector(".bar__label");
      const num = bar.querySelector(".bar__num");
      if (!fill || !label) return;
      const target = fill.style.width || "0%";
      const text = label.textContent.trim() + " " + (num ? num.textContent.trim() : target);
      bar.setAttribute("aria-label", text);
      fill.setAttribute("title", text);
      if (reduce) {
        fill.style.width = target;
        return;
      }
      fill.style.width = "0%";
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          fill.style.width = target;
        });
      });
    });
  }

  function paintColumns(root) {
    const bars = root.querySelectorAll(".chart__bar");
    const labels = root.querySelectorAll(".chart__label");
    bars.forEach(function (bar, index) {
      const label = labels[index];
      const name = label ? label.querySelector(".chart__name") : null;
      const num = label ? label.querySelector(".chart__num") : null;
      if (bar.classList.contains("chart__bar--zero")) return;
      const height = parseFloat(bar.style.height) || 0;
      bar.style.height = Math.max(height, 0.8).toFixed(1) + "%";
      const text = (name ? name.textContent.trim() : "") + " " +
        (num ? num.textContent.trim() : "");
      bar.setAttribute("title", text);
      bar.setAttribute("aria-label", text);
    });
    root.setAttribute("role", "img");
    root.setAttribute("aria-label", "各列缺失率柱图");
  }

  function boot() {
    document.querySelectorAll("[data-bars]").forEach(paintBars);
    document.querySelectorAll("[data-chart]").forEach(paintColumns);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
