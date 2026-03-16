import type { JSX } from 'react'
import { useState, useEffect } from 'react'
import './App.css'
import MapView from './components/MapView'
import MissionLog from './components/MissionLog'
import DroneStatus from './components/DroneStatus'
import { Drone, SurvivorPoint, MissionLogEntry } from './types'

function App(): JSX.Element {
  // Mock data - replace with real API calls
  const [drones, setDrones] = useState<Drone[]>([
    {
      id: 'ALPHA-01',
      latitude: 40.7128,
      longitude: -74.006,
      battery: 85,
      currentMission: 'Sector A reconnaissance',
      status: 'active',
      altitude: 150,
    },
    {
      id: 'BETA-02',
      latitude: 40.7150,
      longitude: -74.008,
      battery: 60,
      currentMission: 'Survivor search - Grid 2',
      status: 'active',
      altitude: 200,
    },
    {
      id: 'GAMMA-03',
      latitude: 40.7100,
      longitude: -74.005,
      battery: 40,
      currentMission: 'Returning to base',
      status: 'returning',
      altitude: 50,
    },
  ])

  const [_survivors] = useState<SurvivorPoint[]>([
    {
      id: 'SUR-001',
      latitude: 40.715,
      longitude: -74.007,
      probability: 0.95,
      lastDetected: new Date(),
    },
    {
      id: 'SUR-002',
      latitude: 40.712,
      longitude: -74.009,
      probability: 0.72,
      lastDetected: new Date(),
    },
    {
      id: 'SUR-003',
      latitude: 40.710,
      longitude: -74.004,
      probability: 0.45,
      lastDetected: new Date(),
    },
  ])

  const [logs, setLogs] = useState<MissionLogEntry[]>([
    {
      id: '1',
      timestamp: new Date(Date.now() - 10000),
      droneId: 'ALPHA-01',
      message: 'Drone A initialized with 85% battery. Assigned to Sector A reconnaissance.',
      type: 'info',
    },
    {
      id: '2',
      timestamp: new Date(Date.now() - 8000),
      droneId: 'BETA-02',
      message: 'Drone B has 60% battery. Switching to survivor search - Grid 2.',
      type: 'info',
    },
    {
      id: '3',
      timestamp: new Date(Date.now() - 5000),
      droneId: 'GAMMA-03',
      message: 'Drone C battery critical at 40%. Initiating return to base.',
      type: 'warning',
    },
    {
      id: '4',
      timestamp: new Date(Date.now() - 2000),
      droneId: 'BETA-02',
      message: 'High probability survivor detected at coordinates 40.715, -74.007. Human confirmation needed.',
      type: 'success',
    },
  ])

  // Simulate drone movement
  useEffect(() => {
    const interval = setInterval(() => {
      setDrones((prevDrones) =>
        prevDrones.map((drone) => ({
          ...drone,
          latitude: drone.latitude + (Math.random() - 0.5) * 0.001,
          longitude: drone.longitude + (Math.random() - 0.5) * 0.001,
          battery: Math.max(0, drone.battery - Math.random() * 0.5),
          altitude: drone.status === 'returning' ? Math.max(0, drone.altitude - 5) : drone.altitude,
        }))
      )
    }, 2000)

    return () => clearInterval(interval)
  }, [])

  // Simulate mission log updates
  useEffect(() => {
    const interval = setInterval(() => {
      const messages = [
        'Scanning sector for survivors...',
        'Coverage map updated. New hot spots identified.',
        'Collision avoidance: 3 potential conflicts ahead.',
        'Signal strength improving. Focusing search area.',
        'Weather conditions stable. Mission proceeding.',
        'Battery optimization: extending mission duration by 15%.',
      ]

      const droneIds = drones.map((d) => d.id)
      const randomDrone = droneIds[Math.floor(Math.random() * droneIds.length)]
      const randomMessage = messages[Math.floor(Math.random() * messages.length)]

      const newLog: MissionLogEntry = {
        id: Date.now().toString(),
        timestamp: new Date(),
        droneId: randomDrone,
        message: randomMessage,
        type: Math.random() > 0.7 ? 'warning' : 'info',
      }

      setLogs((prevLogs) => [...prevLogs, newLog].slice(-50)) // Keep last 50 logs
    }, 5000)

    return () => clearInterval(interval)
  }, [drones])

  return (
    <div className="w-screen h-screen bg-slate-900 flex overflow-hidden">
      {/* Left Sidebar - Mission Log */}
      <div className="w-1/4 h-screen flex flex-col border-r border-slate-700">
        <MissionLog logs={logs} isStreaming={true} />
      </div>

      {/* Center - Map View */}
      <div className="flex-1 h-screen flex flex-col">
        <div className="bg-linear-to-r from-slate-900 to-slate-800 text-white px-6 py-4 border-b border-slate-700">
          <h1 className="text-2xl font-bold tracking-widest">DRONE ORCHESTRATION CONTROL</h1>
          <p className="text-xs text-slate-300 mt-1">Real-time disaster zone monitoring and rescue coordination</p>
        </div>
        <div className="flex-1 p-4">
          <MapView drones={drones} survivors={_survivors} centerLat={40.7128} centerLng={-74.006} />
        </div>
      </div>

      {/* Right Sidebar - Drone Status */}
      <div className="w-1/4 h-screen flex flex-col border-l border-slate-700">
        <DroneStatus drones={drones} />
      </div>
    </div>
  )
}

export default App
