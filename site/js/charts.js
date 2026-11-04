/**
 * High-performance Canvas event curve chart renderer.
 */

function renderEventCurveChart(canvasId, curveData, marketProxy = false) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !curveData || curveData.length === 0) return;

  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;

  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const width = rect.width;
  const height = rect.height;
  const padding = { top: 30, right: 30, bottom: 40, left: 55 };

  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  // Clear
  ctx.clearRect(0, 0, width, height);

  // Range
  const offsets = curveData.map(d => d.offset);
  const minOffset = Math.min(...offsets);
  const maxOffset = Math.max(...offsets);

  const retValues = curveData.map(d => d.return_from_d0);
  const abValues = curveData.map(d => d.abnormal_return);
  const allValues = [...retValues, ...abValues, 0];

  let minVal = Math.min(...allValues);
  let maxVal = Math.max(...allValues);
  // Add margin
  const valMargin = (maxVal - minVal) * 0.1 || 0.02;
  minVal -= valMargin;
  maxVal += valMargin;

  const xToPixel = off => padding.left + ((off - minOffset) / (maxOffset - minOffset)) * plotWidth;
  const yToPixel = val => padding.top + plotHeight - ((val - minVal) / (maxVal - minVal)) * plotHeight;

  // Draw grid & zero lines
  ctx.strokeStyle = "#334155";
  ctx.lineWidth = 1;

  // Zero line
  const zeroY = yToPixel(0);
  ctx.beginPath();
  ctx.setLineDash([4, 4]);
  ctx.moveTo(padding.left, zeroY);
  ctx.lineTo(width - padding.right, zeroY);
  ctx.stroke();

  // D0 vertical line
  const d0X = xToPixel(0);
  ctx.strokeStyle = "#475569";
  ctx.beginPath();
  ctx.moveTo(d0X, padding.top);
  ctx.lineTo(d0X, height - padding.bottom);
  ctx.stroke();
  ctx.setLineDash([]);

  // Labels
  ctx.fillStyle = "#94a3b8";
  ctx.font = "11px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("D-60", xToPixel(-60), height - padding.bottom + 18);
  ctx.fillText("D-30", xToPixel(-30), height - padding.bottom + 18);
  ctx.fillText("D0", d0X, height - padding.bottom + 18);
  ctx.fillText("D+20", xToPixel(20), height - padding.bottom + 18);

  ctx.textAlign = "right";
  ctx.fillText((maxVal * 100).toFixed(1) + "%", padding.left - 8, padding.top + 10);
  ctx.fillText("0.0%", padding.left - 8, zeroY + 4);
  ctx.fillText((minVal * 100).toFixed(1) + "%", padding.left - 8, height - padding.bottom);

  // Helper to draw series
  function drawSeries(key, color, lineWidth) {
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.beginPath();
    let started = false;

    for (const pt of curveData) {
      const val = pt[key];
      if (val === undefined || isNaN(val)) continue;
      const x = xToPixel(pt.offset);
      const y = yToPixel(val);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();
  }

  // 1. Stock Return curve (Blue)
  drawSeries("return_from_d0", "#38bdf8", 2);

  // 2. Abnormal Return curve (Green)
  if (!marketProxy) drawSeries("abnormal_return", "#4ade80", 2.5);

  // Legend
  ctx.textAlign = "left";
  ctx.font = "12px sans-serif";

  // Blue
  ctx.fillStyle = "#38bdf8";
  ctx.fillRect(width - 240, 12, 14, 4);
  ctx.fillStyle = "#cbd5e1";
  ctx.fillText("절대수익률", width - 220, 18);

  if (marketProxy) return;

  // Green
  ctx.fillStyle = "#4ade80";
  ctx.fillRect(width - 130, 12, 14, 4);
  ctx.fillStyle = "#cbd5e1";
  ctx.fillText("초과수익률 (CAR)", width - 110, 18);
}
