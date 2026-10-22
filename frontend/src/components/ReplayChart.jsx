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

export default function ReplayChart({ series, metric, threshold, firstAlertS, color }) {
  const pts = series
    .map((p) => ({ x: p.t_s / 60, y: p[metric], flag: p.flag }))
    .filter((p) => p.y != null)
  if (pts.length === 0) return <p className="empty">No values for this measurement in the trial.</p>

  const ys = pts.map((p) => p.y)
  const lo = Math.min(...ys, metric === 'score' ? threshold : Infinity)
  const hi = Math.max(...ys, metric === 'score' ? threshold : -Infinity)
  const pad = (hi - lo || 1) * 0.08
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
  const end = series[series.length - 1].t_s / 60
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
  if (firstAlertS != null) {
    datasets.push({
      label: 'First alert',
      borderColor: '#14213d',
      borderDash: [2, 3],
      borderWidth: 1.5,
      pointRadius: 0,
      data: [{ x: firstAlertS / 60, y: lo - pad }, { x: firstAlertS / 60, y: hi + pad }],
    })
  }
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    parsing: false,
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    scales: {
      x: { type: 'linear', min: 0, max: end, title: { display: true, text: 'minutes since trial start' } },
      y: { min: lo - pad, max: hi + pad, title: { display: true, text: METRICS[metric].label } },
    },
    plugins: { legend: { position: 'top' } },
  }
  return (
    <div className="chart-box">
      <Line data={{ datasets }} options={options} />
    </div>
  )
}