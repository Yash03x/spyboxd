import React from 'react';
import { motion } from 'framer-motion';
import { LucideIcon } from 'lucide-react';

interface StatsCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  trend?: {
    value: number;
    isPositive: boolean;
  };
  gradient?: string;
  delay?: number;
}

const StatsCard: React.FC<StatsCardProps> = ({ 
  title, 
  value, 
  subtitle, 
  icon: Icon, 
  trend,
  gradient = "from-cinema-500/20 to-cinema-600/10",
  delay = 0
}) => {
  return (
    <motion.div
      className={`stat-card group relative overflow-hidden bg-gradient-to-br ${gradient} backdrop-blur-md rounded-2xl border border-cinema-400/20 p-6 hover:border-cinema-400/40 transition-all duration-500`}
      initial={{ opacity: 0, y: 20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ 
        duration: 0.6, 
        delay,
        ease: [0.25, 0.46, 0.45, 0.94]
      }}
      whileHover={{ 
        scale: 1.02,
        y: -5,
        transition: { duration: 0.2 }
      }}
    >
      {/* Animated background gradient */}
      <div
        aria-hidden="true"
        data-testid="stats-card-shimmer"
        className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-cinema-400/5 to-transparent opacity-0 group-hover:translate-x-full group-hover:opacity-100 group-hover:transition-transform group-hover:duration-1000 group-hover:ease-linear"
      />

      <div className="relative z-10">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <motion.div 
            className="p-3 bg-cinema-500/20 rounded-xl border border-cinema-400/30"
            whileHover={{ scale: 1.1, rotate: 5 }}
            transition={{ type: "spring", stiffness: 400, damping: 10 }}
          >
            <Icon className="w-6 h-6 text-cinema-400" />
          </motion.div>
          
          {trend && (
            <motion.div 
              className={`flex items-center space-x-1 px-2 py-1 rounded-lg text-xs font-medium ${
                trend.isPositive 
                  ? 'bg-green-500/20 text-green-400 border border-green-500/30' 
                  : 'bg-red-500/20 text-red-400 border border-red-500/30'
              }`}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: delay + 0.3 }}
            >
              <span>{trend.isPositive ? '↑' : '↓'}</span>
              <span>{Math.abs(trend.value)}%</span>
            </motion.div>
          )}
        </div>

        {/* Main Value */}
        <motion.div 
          className="mb-2"
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: delay + 0.2, duration: 0.5 }}
        >
          <h3 className="text-3xl font-bold text-white text-glow">
            {typeof value === 'number' ? value.toLocaleString() : value}
          </h3>
        </motion.div>

        {/* Title and Subtitle */}
        <div>
          <h4 className="font-semibold text-white/90 text-sm mb-1">{title}</h4>
          {subtitle && (
            <p className="text-white/60 text-xs">{subtitle}</p>
          )}
        </div>

        {/* Decorative corner accent */}
        <div className="absolute top-0 right-0 w-20 h-20 bg-gradient-to-bl from-cinema-400/10 to-transparent rounded-bl-full" />
      </div>
    </motion.div>
  );
};

export default StatsCard;
