import { Line } from 'react-chartjs-2'
import { Chart as ChartJS, LinearScale, PointElement, LineElement, Tooltip, Legend } from 'chart.js'
import { usePolling } from '../api'

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Legend)

const COLORS = { 1: '#0e7c86', 2: '#e8743b' }
// minSpan keeps tiny sensor noise from being stretched across the whole chart.
const METRICS = {
  water: { label: 'Distance to surface (cm)', minSpan: 2 },
  flow: { label: 'Flow (L/min)', minSpan: 2 },
  mq4: { label: 'MQ-4 (V)', minSpan: 0.1 },
  mq135: { label: 'MQ-135 (V)', minSpan: 0.1, nodes: ['1'] },
}

export default function TrendChart({ metric, minutes }) {
  const { data, error } = usePolling(`/api/series?minutes=${minutes}`, 5000)
  if (error) return <p className="empty">Could not load history ({error})</p>
  if (!data) return <p className="empty">Loading…</p>

  const nodes = METRICS[metric].nodes ?? ['1', '2']
  const datasets = nodes.map((n) => ({
    label: `Node ${n}`,
    borderColor: COLORS[n],
    backgroundColor: COLORS[n],
    borderWidth: 1.5,
    pointRadius: 0,
    tension: 0.2,
    spanGaps: false,
    data: (data[n] ?? []).map((p) => ({ x: -p.age_s / 60, y: p[metric] })),
  }))

  if (datasets.every((d) => d.data.length === 0)) {
    return <p className="empty">No readings in the last {minutes} minutes. Power the nodes to see live data.</p>
  }

  const ys = datasets.flatMap((d) => d.data.map((p) => p.y)).filter((v) => v != null)
  let yMin, yMax
  if (ys.length) {
    const lo = Math.min(...ys)
    const hi = Math.max(...ys)
    const span = METRICS[metric].minSpan
    if (hi - lo < span) {
      const mid = (hi + lo) / 2
      yMin = mid - span / 2
      yMax = mid + span / 2
    }
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    scales: {
      x: {
        type: 'linear',
        min: -minutes,
        max: 0,
        title: { display: true, text: 'minutes ago' },
        ticks: { callback: (v) => (v === 0 ? 'now' : v) },
      },
      y: { min: yMin, max: yMax, title: { display: true, text: METRICS[metric].label } },
    },
    plugins: { legend: { position: 'top' } },
  }

  return (
    <div className="chart-box">
      <Line data={{ datasets }} options={options} />
    </div>
  )
}