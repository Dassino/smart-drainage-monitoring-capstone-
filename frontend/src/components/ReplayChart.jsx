import { Line } from 'react-chartjs-2'
import { Chart as ChartJS, LinearScale, PointElement, LineElement, Tooltip, Legend } from 'chart.js'

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Legend)

export const METRICS = {
  score: { label: 'Anomaly score (higher = less normal)' },
  water: { label: 'Distance to surface (cm)' },
  flow: { label: 'Flow (L/min)' },
  mq4: { label: 'MQ-4 (V)' },
  mq135: { label: 'MQ-135 (V)', node1Only: true },
}

const EVENT_STYLE = {
  onset: { label: 'Event starts', color: '#14213d', dash: [2, 3], width: 2 },
  critical: { label: 'Critical level', color: '#b3191f', dash: [], width: 2 },
  end: { label: 'Event ends', color: '#5b6785', dash: [4, 3], width: 1.5 },
}

// Vertical lines at the given x positions, as one dataset (null points break the line between them).
function vlines(label, xs, lo, hi, color, dash, width) {
  return {
    label,
    borderColor: color,
    borderDash: dash,
    borderWidth: width,
    pointRadius: 0,
    spanGaps: false,
    data: xs.flatMap((x) => [{ x, y: lo }, { x, y: hi }, { x, y: null }]),
  }
}

export default function ReplayChart({ series, metric, threshold, episodes = [], events = [], gaps = [], color }) {
  const pts = series
    .map((p) => ({ x: p.rec_s / 60, y: p[metric], flag: p.flag }))
    .filter((p) => p.y != null)
  if (pts.length === 0) return <p className="empty">No values for this measurement in the trial.</p>

  const ys = pts.map((p) => p.y)
  const lo = Math.min(...ys, metric === 'score' ? threshold : Infinity)
  const hi = Math.max(...ys, metric === 'score' ? threshold : -Infinity)
  const pad = (hi - lo || 1) * 0.08
  const yLo = lo - pad
  const yHi = hi + pad
  const end = series[series.length - 1].rec_s / 60

  const datasets = [
    {
      label: METRICS[metric].label,
      borderColor: color,
      backgroundColor: color,
      borderWidth: 1.2,
      pointRadius: metric === 'score' ? pts.map((p) => (p.flag ? 2.5 : 0)) : 0,
      pointBackgroundColor: pts.map((p) => (metric === 'score' && p.flag ? '#b3191f' : color)),
      data: pts,
    },
  ]
  if (metric === 'score') {
    datasets.push({
      label: 'Alarm threshold',
      borderColor: '#b3191f',
      borderDash: [6, 4],
      borderWidth: 1.5,
      pointRadius: 0,
      data: [{ x: 0, y: threshold }, { x: end, y: threshold }],
    })
  }
  if (gaps.length) {
    datasets.push(vlines('Recording gap', gaps.map((g) => g / 60), yLo, yHi, '#9aa6bd', [1, 3], 1.5))
  }
  if (episodes.length) {
    datasets.push(vlines('Alert raised', episodes.map((e) => e.start_s / 60), yLo, yHi, '#8a5200', [], 1.5))
  }
  Object.entries(EVENT_STYLE).forEach(([type, st]) => {
    const xs = events.filter((e) => e.type === type).map((e) => e.rec_s / 60)
    if (xs.length) datasets.push(vlines(st.label, xs, yLo, yHi, st.color, st.dash, st.width))
  })

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    parsing: false,
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    scales: {
      x: { type: 'linear', min: 0, max: end, title: { display: true, text: 'minutes of recording (gaps removed)' } },
      y: { min: yLo, max: yHi, title: { display: true, text: METRICS[metric].label } },
    },
    plugins: { legend: { position: 'top' } },
  }
  return (
    <div className="chart-box">
      <Line data={{ datasets }} options={options} />
    </div>
  )
}