import React from 'react';
import { motion } from 'framer-motion';
import { 
  UserIcon, 
  CalendarIcon, 
  StarIcon, 
  FilmIcon,
  ChatBubbleLeftIcon,
  ClockIcon,
  ArrowPathIcon,
  TrashIcon
} from '@heroicons/react/24/outline';
import { ProfileInfo } from '../services/api';

interface ProfileCardProps {
  profile: ProfileInfo;
  index: number;
  onDelete?: (username: string) => void;
  isDeleting?: boolean;
}

const ProfileCard: React.FC<ProfileCardProps> = ({ 
  profile, 
  index, 
  onDelete,
  isDeleting = false 
}) => {
  const handleDelete = () => {
    if (onDelete && !isDeleting && window.confirm(`Are you sure you want to delete the profile for @${profile.username}? This action cannot be undone.`)) {
      onDelete(profile.username);
    }
  };

  const getSyncStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'bg-green-500/20 text-green-400 border-green-500/30';
      case 'in_progress':
        return 'bg-cinema-500/20 text-cinema-400 border-cinema-500/30';
      case 'error':
        return 'bg-red-500/20 text-red-400 border-red-500/30';
      default:
        return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
    }
  };

  const getSyncStatusText = (status: string) => {
    switch (status) {
      case 'completed':
        return 'Synced';
      case 'in_progress':
        return 'Syncing...';
      case 'error':
        return 'Error';
      default:
        return 'Awaiting sync';
    }
  };

  return (
    <motion.div
      className="card-cinema group relative overflow-hidden"
      initial={{ opacity: 0, y: 30, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ 
        duration: 0.6, 
        delay: index * 0.1,
        ease: [0.25, 0.46, 0.45, 0.94]
      }}
      whileHover={{ 
        scale: 1.02,
        y: -5,
        transition: { duration: 0.2 }
      }}
    >
      {/* Profile Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center space-x-4">
          <motion.div 
            className="w-12 h-12 bg-gradient-to-br from-cinema-400 to-cinema-600 rounded-full flex items-center justify-center shadow-glow"
            whileHover={{ rotate: 360, scale: 1.1 }}
            transition={{ duration: 0.6, ease: "easeInOut" }}
          >
            <UserIcon className="w-6 h-6 text-white" />
          </motion.div>
          
          <div>
            <motion.h3 
              className="text-lg font-bold text-white group-hover:text-cinema-300 transition-colors"
              initial={{ x: -10, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              transition={{ delay: index * 0.1 + 0.2 }}
            >
              @{profile.username}
            </motion.h3>
            <motion.div 
              className={`inline-flex items-center px-2 py-1 rounded-lg text-xs font-medium border ${getSyncStatusColor(profile.scraping_status || 'pending')}`}
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ delay: index * 0.1 + 0.3 }}
            >
              {profile.scraping_status === 'in_progress' && (
                <ArrowPathIcon className="w-3 h-3 mr-1 animate-spin" />
              )}
              {getSyncStatusText(profile.scraping_status || 'pending')}
            </motion.div>
          </div>
        </div>

      {/* Action Buttons */}
      <div className="flex items-center space-x-2">
          {onDelete && (
            <motion.button
              onClick={handleDelete}
              disabled={isDeleting}
              className={`p-2 rounded-lg transition-all duration-300 ${
                isDeleting
                  ? 'bg-red-500/20 cursor-not-allowed'
                  : 'bg-red-500/20 hover:bg-red-500/30 hover:scale-110'
              }`}
              whileHover={!isDeleting ? { scale: 1.1 } : {}}
              whileTap={!isDeleting ? { scale: 0.95 } : {}}
              title="Delete profile"
            >
              <TrashIcon className={`w-4 h-4 text-red-400 ${isDeleting ? 'animate-pulse' : ''}`} />
            </motion.button>
          )}
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        <motion.div 
          className="bg-white/5 rounded-xl p-4 border border-white/10"
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: index * 0.1 + 0.4 }}
        >
          <div className="flex items-center space-x-2 mb-2">
            <FilmIcon className="w-4 h-4 text-cinema-400" />
            <span className="text-xs text-white/60 font-medium">Movies</span>
          </div>
          <div className="text-xl font-bold text-white">
            {profile.total_films?.toLocaleString() || '0'}
          </div>
        </motion.div>

        <motion.div 
          className="bg-white/5 rounded-xl p-4 border border-white/10"
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: index * 0.1 + 0.5 }}
        >
          <div className="flex items-center space-x-2 mb-2">
            <StarIcon className="w-4 h-4 text-yellow-400" />
            <span className="text-xs text-white/60 font-medium">Avg Rating</span>
          </div>
          <div className="text-xl font-bold text-white">
            {profile.avg_rating?.toFixed(1) || '0.0'}
          </div>
        </motion.div>

        <motion.div 
          className="bg-white/5 rounded-xl p-4 border border-white/10"
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: index * 0.1 + 0.6 }}
        >
          <div className="flex items-center space-x-2 mb-2">
            <ChatBubbleLeftIcon className="w-4 h-4 text-blue-400" />
            <span className="text-xs text-white/60 font-medium">Reviews</span>
          </div>
          <div className="text-xl font-bold text-white">
            {profile.total_reviews?.toLocaleString() || '0'}
          </div>
        </motion.div>

        <motion.div 
          className="bg-white/5 rounded-xl p-4 border border-white/10"
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: index * 0.1 + 0.7 }}
        >
          <div className="flex items-center space-x-2 mb-2">
            <CalendarIcon className="w-4 h-4 text-green-400" />
            <span className="text-xs text-white/60 font-medium">Member Since</span>
          </div>
          <div className="text-sm font-semibold text-white">
            {profile.join_date 
              ? new Date(profile.join_date).getFullYear()
              : 'Unknown'
            }
          </div>
        </motion.div>
      </div>

      {/* Last Updated */}
      {profile.last_scraped_at && (
        <motion.div 
          className="flex items-center space-x-2 text-xs text-white/50"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: index * 0.1 + 0.8 }}
        >
          <ClockIcon className="w-3 h-3" />
          <span>
            Updated {new Date(profile.last_scraped_at).toLocaleDateString()}
          </span>
        </motion.div>
      )}

      {/* Hover Animation Overlay */}
      <motion.div
        className="absolute inset-0 bg-gradient-to-br from-cinema-500/0 via-cinema-500/5 to-cinema-600/0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-2xl"
        animate={{
          background: [
            'linear-gradient(135deg, rgba(245,124,0,0) 0%, rgba(229,81,0,0.05) 50%, rgba(196,65,0,0) 100%)',
            'linear-gradient(225deg, rgba(245,124,0,0) 0%, rgba(229,81,0,0.05) 50%, rgba(196,65,0,0) 100%)',
            'linear-gradient(135deg, rgba(245,124,0,0) 0%, rgba(229,81,0,0.05) 50%, rgba(196,65,0,0) 100%)',
          ],
        }}
        transition={{ duration: 3, repeat: Infinity, ease: 'linear' }}
      />
    </motion.div>
  );
};

export default ProfileCard;
