import React from 'react';
import { motion } from 'framer-motion';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
  ChartOptions,
} from 'chart.js';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

interface ActivityData {
  month: string;
  movies_watched: number;
  average_rating: number | null;
  is_partial: boolean;
}

interface ActivityChartProps {
  data: ActivityData[];
  title?: string;
}

function formatMonth(monthValue: string, month: 'short' | 'long', year: '2-digit' | 'numeric') {
  const [yearValue, monthValuePart] = monthValue.split('-').map(Number);
  const date = new Date(Date.UTC(yearValue, monthValuePart - 1, 1));
  return date.toLocaleDateString('en-US', { month, year, timeZone: 'UTC' });
}

const ActivityChart: React.FC<ActivityChartProps> = ({ 
  data, 
  title = "Watching Activity" 
}) => {
  const partialPoint = data.find((item) => item.is_partial);
  const completedPoints = data.filter((item) => !item.is_partial);
  const completedTotal = completedPoints.reduce((sum, item) => sum + item.movies_watched, 0);
  const completedAverage = completedPoints.length > 0
    ? completedTotal / completedPoints.length
    : null;
  const partialMonth = partialPoint
    ? formatMonth(partialPoint.month, 'long', 'numeric')
    : null;
  const chartAccessibilityLabel = partialMonth
    ? `${title}. ${partialMonth} is month to date and is excluded from the completed-month average. ${completedAverage === null ? 'No completed-month average is available.' : `Average: ${completedAverage.toFixed(1)} watch events per completed month.`}`
    : `${title}. ${completedAverage === null ? 'No completed-month average is available.' : `Average: ${completedAverage.toFixed(1)} watch events per completed month.`}`;

  const chartData = {
    labels: data.map((item) => (
      `${formatMonth(item.month, 'short', '2-digit')}${item.is_partial ? ' (MTD)' : ''}`
    )),
    datasets: [
      {
        label: 'Watch Events',
        data: data.map(item => item.movies_watched),
        borderColor: '#f57c00',
        backgroundColor: 'rgba(245, 124, 0, 0.1)',
        borderWidth: 3,
        fill: true,
        tension: 0.4,
        pointBackgroundColor: '#f57c00',
        pointBorderColor: '#ffffff',
        pointBorderWidth: 2,
        pointRadius: 6,
        pointHoverRadius: 8,
        pointHoverBackgroundColor: '#e65100',
        pointHoverBorderColor: '#ffffff',
        pointHoverBorderWidth: 3,
      },
      {
        label: 'Average Rating',
        data: data.map(item => item.average_rating !== null ? item.average_rating * 10 : null), // Scale to make visible
        borderColor: '#64748b',
        backgroundColor: 'rgba(100, 116, 139, 0.1)',
        borderWidth: 2,
        fill: false,
        tension: 0.4,
        pointBackgroundColor: '#64748b',
        pointBorderColor: '#ffffff',
        pointBorderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 6,
        borderDash: [5, 5],
        yAxisID: 'rating-axis',
      },
    ],
  };

  const options: ChartOptions<'line'> = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      intersect: false,
      mode: 'index' as const,
    },
    scales: {
      x: {
        grid: {
          color: 'rgba(255, 255, 255, 0.1)',
        },
        ticks: {
          color: '#cbd5e1',
          font: {
            family: 'Inter',
            size: 11,
          },
        },
      },
      y: {
        position: 'left' as const,
        grid: {
          color: 'rgba(255, 255, 255, 0.1)',
        },
        ticks: {
          color: '#cbd5e1',
          font: {
            family: 'Inter',
            size: 11,
          },
        },
        title: {
          display: true,
          text: 'Watch Events',
          color: '#f57c00',
          font: {
            family: 'Inter',
            size: 12,
            weight: 'bold',
          },
        },
      },
      'rating-axis': {
        type: 'linear' as const,
        position: 'right' as const,
        grid: {
          drawOnChartArea: false,
        },
        ticks: {
          color: '#64748b',
          font: {
            family: 'Inter',
            size: 11,
          },
          callback: function(value) {
            return ((value as number) / 10).toFixed(1); // Convert back to rating scale
          },
        },
        title: {
          display: true,
          text: 'Avg Rating',
          color: '#64748b',
          font: {
            family: 'Inter',
            size: 12,
            weight: 'bold',
          },
        },
        min: 0,
        max: 50, // 5.0 rating * 10
      },
    },
    plugins: {
      legend: {
        display: true,
        position: 'top' as const,
        labels: {
          color: '#f8fafc',
          font: {
            family: 'Inter',
            size: 12,
          },
          padding: 20,
          usePointStyle: true,
        },
      },
      tooltip: {
        backgroundColor: 'rgba(15, 23, 42, 0.9)',
        titleColor: '#f8fafc',
        bodyColor: '#f8fafc',
        borderColor: '#f57c00',
        borderWidth: 1,
        cornerRadius: 8,
        padding: 12,
        callbacks: {
          label: (context) => {
            const periodSuffix = data[context.dataIndex]?.is_partial ? ' (MTD)' : '';
            if (context.dataset.label === 'Average Rating') {
              const rating = (context.raw as number) / 10;
              return `${context.dataset.label}${periodSuffix}: ${rating.toFixed(1)} ⭐`;
            }
            return `${context.dataset.label}${periodSuffix}: ${context.raw}`;
          },
        },
      },
    },
    animation: {
      duration: 2000,
      easing: 'easeInOutQuart',
    },
  };

  return (
    <motion.section
      aria-label={title}
      className="card-cinema h-96"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay: 0.1 }}
    >
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-lg font-semibold text-white">{title}</h3>
          <p className="text-white/60 text-sm">
            {partialMonth
              ? `Monthly watch events · ${partialMonth} is month to date; average uses completed months`
              : 'Monthly watch events'}
          </p>
        </div>
        
        <motion.div 
          className="text-center"
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.4 }}
        >
          <output
            aria-label="Average watch events per completed month"
            className="block text-xl font-bold text-cinema-400"
          >
            {completedAverage === null ? '—' : completedAverage.toFixed(1)}
          </output>
          <div className="text-xs text-white/60">Avg/Completed Month</div>
        </motion.div>
      </div>
      
      <div className="h-72">
        {data.length > 0 ? (
          <motion.div 
            className="h-full"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 1, delay: 0.3 }}
          >
            <Line
              aria-label={chartAccessibilityLabel}
              data={chartData}
              options={options}
              role="img"
            />
            <ul className="sr-only" aria-label={`${title} data points`}>
              {data.map((item) => (
                <li key={item.month}>
                  {formatMonth(item.month, 'long', 'numeric')}
                  {item.is_partial ? ', month to date' : ''}: {item.movies_watched} watch events;{' '}
                  {item.average_rating === null
                    ? 'average rating unavailable'
                    : `average rating ${item.average_rating.toFixed(1)}`}
                </li>
              ))}
            </ul>
          </motion.div>
        ) : (
          <motion.div 
            className="h-full flex items-center justify-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
          >
            <div className="text-center">
              <div className="w-16 h-16 bg-cinema-500/20 rounded-full flex items-center justify-center mb-3 mx-auto">
                <span className="text-2xl">📈</span>
              </div>
              <p className="text-white/60">No activity data available</p>
            </div>
          </motion.div>
        )}
      </div>
    </motion.section>
  );
};

export default ActivityChart;
