import React, { useEffect, useRef } from 'react'
import { MissionLogEntry } from '../types'

interface MissionLogProps {
  logs: MissionLogEntry[]
  isStreaming?: boolean
}

const MissionLog: React.FC<MissionLogProps> = ({ logs, isStreaming = false }) => {
  const logContainerRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }, [logs])

  const getLogTypeStyles = (type: MissionLogEntry['type']) => {
    switch (type) {
      case 'success':
        return 'border-l-4 border-green-500 bg-green-50 text-green-800'
      case 'error':
        return 'border-l-4 border-red-500 bg-red-50 text-red-800'
      case 'warning':
        return 'border-l-4 border-yellow-500 bg-yellow-50 text-yellow-800'
      case 'info':
      default:
        return 'border-l-4 border-blue-500 bg-blue-50 text-blue-800'
    }
  }

  const getTypeIcon = (type: MissionLogEntry['type']) => {
    switch (type) {
      case 'success':
        return '✓'
      case 'error':
        return '✕'
      case 'warning':
        return '⚠'
      case 'info':
      default:
        return 'ℹ'
    }
  }

  return (
    <div className="flex flex-col h-full bg-white rounded-lg shadow-lg overflow-hidden">
      {/* Header */}
      <div className="bg-linear-to-r from-slate-900 to-slate-800 text-white px-6 py-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold tracking-wide">MISSION LOG</h2>
          <p className="text-xs text-slate-300 mt-1">Agent Reasoning Stream</p>
        </div>
        {isStreaming && (
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
            <span className="text-xs text-slate-300">LIVE</span>
          </div>
        )}
      </div>

      {/* Log entries container */}
      <div ref={logContainerRef} className="flex-1 overflow-y-auto p-4 space-y-3">
        {logs.length === 0 ? (
          <div className="flex items-center justify-center h-full text-slate-400">
            <p className="text-sm">Waiting for mission logs...</p>
          </div>
        ) : (
          logs.map((log) => (
            <div
              key={log.id}
              className={`p-3 rounded text-sm ${getLogTypeStyles(log.type)} transition-all duration-300`}
            >
              <div className="flex items-start gap-3">
                <span className="text-lg font-bold leading-none">{getTypeIcon(log.type)}</span>
                <div className="flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-semibold text-xs opacity-80">{log.droneId}</p>
                    <span className="text-xs opacity-60">
                      {new Date(log.timestamp).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                    </span>
                  </div>
                  <p className="mt-1 leading-relaxed">{log.message}</p>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-slate-200 px-6 py-3 bg-slate-50 text-xs text-slate-600">
        <p>{logs.length} mission events logged</p>
      </div>
    </div>
  )
}

export default MissionLog
