import React from 'react'
import { Drone } from '../types'

interface DroneStatusProps {
  drones: Drone[]
}

const DroneStatus: React.FC<DroneStatusProps> = ({ drones }) => {
  const getStatusColor = (status: Drone['status']) => {
    switch (status) {
      case 'active':
        return 'bg-green-100 text-green-800 border-green-300'
      case 'idle':
        return 'bg-slate-100 text-slate-800 border-slate-300'
      case 'returning':
        return 'bg-yellow-100 text-yellow-800 border-yellow-300'
      case 'charging':
        return 'bg-blue-100 text-blue-800 border-blue-300'
      default:
        return 'bg-slate-100 text-slate-800 border-slate-300'
    }
  }

  const getBatteryColor = (battery: number) => {
    if (battery > 70) return 'bg-green-500'
    if (battery > 40) return 'bg-yellow-500'
    return 'bg-red-500'
  }

  const getBatteryTextColor = (battery: number) => {
    if (battery > 70) return 'text-green-700'
    if (battery > 40) return 'text-yellow-700'
    return 'text-red-700'
  }

  return (
    <div className="flex flex-col h-full bg-white rounded-lg shadow-lg overflow-hidden">
      {/* Header */}
      <div className="bg-linear-to-r from-slate-900 to-slate-800 text-white px-6 py-4">
        <h2 className="text-lg font-bold tracking-wide">DRONE STATUS</h2>
        <p className="text-xs text-slate-300 mt-1">{drones.length} Active Drones</p>
      </div>

      {/* Drones container */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {drones.length === 0 ? (
          <div className="flex items-center justify-center h-full text-slate-400">
            <p className="text-sm">No drones active</p>
          </div>
        ) : (
          drones.map((drone) => (
            <div
              key={drone.id}
              className="p-4 border border-slate-200 rounded-lg hover:border-slate-400 hover:shadow-md transition-all duration-200 bg-slate-50"
            >
              {/* Drone ID and Status */}
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-bold text-slate-900">{drone.id}</h3>
                <span className={`text-xs font-semibold px-2 py-1 rounded-full border ${getStatusColor(drone.status)}`}>
                  {drone.status.toUpperCase()}
                </span>
              </div>

              {/* Mission */}
              <p
                className="text-xs text-slate-600 mb-3 truncate"
                title={drone.currentMission}
              >
                <span className="font-semibold">Mission:</span> {drone.currentMission}
              </p>

              {/* Battery Bar */}
              <div className="mb-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-semibold text-slate-700">Battery</span>
                  <span className={`text-xs font-bold ${getBatteryTextColor(drone.battery)}`}>
                    {drone.battery}%
                  </span>
                </div>
                <div className="w-full h-2 bg-slate-200 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${getBatteryColor(drone.battery)} transition-all duration-300`}
                    style={{ width: `${drone.battery}%` }}
                  />
                </div>
              </div>

              {/* Coordinates and Altitude */}
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="bg-white p-2 rounded border border-slate-200">
                  <p className="text-slate-600">Latitude</p>
                  <p className="font-mono font-semibold text-slate-900">{drone.latitude.toFixed(4)}°</p>
                </div>
                <div className="bg-white p-2 rounded border border-slate-200">
                  <p className="text-slate-600">Longitude</p>
                  <p className="font-mono font-semibold text-slate-900">{drone.longitude.toFixed(4)}°</p>
                </div>
                <div className="bg-white p-2 rounded border border-slate-200 col-span-2">
                  <p className="text-slate-600">Altitude</p>
                  <p className="font-mono font-semibold text-slate-900">{drone.altitude}m</p>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Footer Stats */}
      {drones.length > 0 && (
        <div className="border-t border-slate-200 px-6 py-3 bg-slate-50 text-xs text-slate-600">
          <div className="flex justify-between">
            <span>
              Active:{' '}
              <span className="font-bold text-green-600">
                {drones.filter((d) => d.status === 'active').length}
              </span>
            </span>
            <span>
              Avg Battery:{' '}
              <span className="font-bold">
                {(drones.reduce((sum, d) => sum + d.battery, 0) / drones.length).toFixed(0)}%
              </span>
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

export default DroneStatus
