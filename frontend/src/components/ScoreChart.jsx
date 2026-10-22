import { Line } from 'react-chartjs-2'
import { Chart as ChartJS, LinearScale, PointElement, LineElement, Tooltip, Legend } from 'chart.js'

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Legend)

export default function ScoreChart({ series, threshold, minutes, color }) {
  const pts = series.filter((p) => p.age_s != null)
  if (pts.length === 0) {
    return <p className="empty">No scored readings in this window yet.</p>
  }
  const data = {
    datasets: [
      {
        label: 'Anomaly score',
        borderColor: color,
        backgroundColor: color,
        borderWidth: 1.5,
        tension: 0.2,
        pointRadius: pts.map((p) => (p.flag ? 3.5 : 0)),
        pointBackgroundColor: pts.map((p) => (p.flag ? '#b3191f' : color)),
        data: pts.map((p) => ({ x: -p.age_s / 60, y: p.score })),
      },
      {
        label: 'Alarm threshold',
        borderColor: '#b3191f',
        borderDash: [6, 4],
        borderWidth: 1.5,
        pointRadius: 0,
        data: [{ x: -minutes, y: threshold }, { x: 0, y: threshold }],
      },
    ],
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
      y: { title: { display: true, text: 'score (higher = less normal)' } },
    },
    plugins: { legend: { position: 'top' } },
  }
  return (
    <div className="chart-box short">
      <Line data={data} options={options} />
    </div>
  )
}