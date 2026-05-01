// Live IMU chart
// ════════════════════════════════════════════════════════════
//  CHART
// ════════════════════════════════════════════════════════════
const chartCtx = document.getElementById('imuChart').getContext('2d');
const imuChart = new Chart(chartCtx, {
  type: 'line',
  data: {
    labels: [],
    datasets: [{
      label: '|a|',
      data: [],
      borderColor: 'oklch(0.595 0.165 43)',
      backgroundColor: (ctx) => {
        const gradient = ctx.chart.ctx.createLinearGradient(0, 0, 0, 200);
        gradient.addColorStop(0, 'oklch(0.595 0.165 43 / 0.25)');
        gradient.addColorStop(1, 'oklch(0.595 0.165 43 / 0.02)');
        return gradient;
      },
      borderWidth: 1.8,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: 0.35,
      fill: true,
    }, {
      label: '|r|',
      data: [],
      borderColor: 'oklch(0.720 0.135 88)',
      backgroundColor: 'oklch(0.720 0.135 88 / 0.06)',
      borderWidth: 1.5,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: 0.35,
      fill: false,
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: true,
    animation: { duration: 0 },
    interaction: { mode: 'index', intersect: false },
    scales: {
      x: {
        ticks: {
          maxTicksLimit: 7,
          color: 'oklch(0.650 0.018 58)',
          font: { family: "'IBM Plex Mono', monospace", size: 10 },
          callback: (_, i, arr) => {
            const sec = -(arr.length - 1 - i);
            return sec === 0 ? 'now' : sec + 's';
          }
        },
        grid: { color: 'oklch(0.880 0.018 72)' },
      },
      y: {
        min: 0,
        ticks: {
          color: 'oklch(0.650 0.018 58)',
          font: { family: "'IBM Plex Mono', monospace", size: 10 },
          maxTicksLimit: 5,
        },
        grid: { color: 'oklch(0.880 0.018 72)' },
      }
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'oklch(0.175 0.025 55)',
        titleFont: { family: "'IBM Plex Mono', monospace", size: 11 },
        bodyFont: { family: "'IBM Plex Mono', monospace", size: 11 },
        callbacks: {
          title: (items) => items[0].label + 's',
          label: (item) => ` ${item.dataset.label} = ${(item.raw || 0).toFixed(3)}`,
        }
      }
    }
  },
  plugins: [{
    id: 'writingBands',
    beforeDatasetsDraw(chart) {
      const { ctx, chartArea: { top, bottom }, scales: { x } } = chart;
      if (!x || !S.chartBuffer.length) return;
      ctx.save();
      S.chartBuffer.forEach((pt, i) => {
        if (!pt.pen_writing) return;
        const xPos = x.getPixelForValue(i);
        const nextX = x.getPixelForValue(i + 1);
        ctx.fillStyle = 'oklch(0.580 0.130 148 / 0.18)';
        ctx.fillRect(xPos, top, (nextX || xPos + 8) - xPos, bottom - top);
      });
      ctx.restore();
    }
  }]
});

export function updateChart(chartPts) {
  if (!chartPts || !chartPts.length) return;
  // Merge new points into buffer (avoid duplicates by timestamp)
  chartPts.forEach(pt => {
    if (!S.chartBuffer.find(b => b.t === pt.t)) {
      S.chartBuffer.push(pt);
    }
  });
  // Keep last 60
  if (S.chartBuffer.length > 60) S.chartBuffer = S.chartBuffer.slice(-60);

  const accVals = S.chartBuffer.map(b => Number(b.acc_mag ?? b.mag ?? 0));
  const gyroVals = S.chartBuffer.map(b => Number(b.gyro_mag ?? 0));
  imuChart.data.labels = S.chartBuffer.map((_, i) => i);
  imuChart.data.datasets[0].data = accVals;
  imuChart.data.datasets[1].data = gyroVals;
  imuChart.update('none');

  // Stats
  const curAcc = accVals[accVals.length - 1] || 0;
  const curGyro = gyroVals[gyroVals.length - 1] || 0;
  S.chartMax = Math.max(S.chartMax, ...accVals, ...gyroVals);
  const writePct = S.chartBuffer.length
    ? Math.round(S.chartBuffer.filter(b => b.pen_writing).length / S.chartBuffer.length * 100)
    : 0;

  document.getElementById('statMag').textContent = curAcc.toFixed(3);
  document.getElementById('statGyro').textContent = curGyro.toFixed(3);
  document.getElementById('statWritePct').textContent = writePct + '%';
}
