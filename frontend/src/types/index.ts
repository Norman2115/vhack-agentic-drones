export interface Drone {
  id: string
  latitude: number
  longitude: number
  battery: number // 0-100
  currentMission: string
  status: 'active' | 'idle' | 'returning' | 'charging'
  altitude: number
}

export interface SurvivorPoint {
  id: string
  latitude: number
  longitude: number
  probability: number // 0-1
  lastDetected: Date
}

export interface MissionLogEntry {
  id: string
  timestamp: Date
  droneId: string
  message: string
  type: 'info' | 'warning' | 'success' | 'error'
}

export interface HeatmapData {
  latitude: number
  longitude: number
  intensity: number // 0-1
}

export interface DisasterZone {
  name: string
  centerLatitude: number
  centerLongitude: number
  radiusKm: number
}
