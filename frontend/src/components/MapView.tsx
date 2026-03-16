import React, { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import * as d3 from 'd3'
import { Drone, SurvivorPoint } from '../types'

interface MapViewProps {
  drones: Drone[]
  survivors: SurvivorPoint[]
  centerLat: number
  centerLng: number
}

const MapView: React.FC<MapViewProps> = ({ drones, survivors, centerLat, centerLng }) => {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const droneMarkersRef = useRef<Map<string, L.Marker>>(new Map())
  const survivorMarkersRef = useRef<Map<string, L.Marker>>(new Map())

  // Initialize map
  useEffect(() => {
    if (!mapContainer.current) return

    // Create map instance
    map.current = L.map(mapContainer.current).setView([centerLat, centerLng], 14)

    // Add tile layer (OpenStreetMap)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 19,
    }).addTo(map.current)

    // Initialize SVG overlay for D3
    const svg = d3
      .select(map.current.getPanes().overlayPane as HTMLElement)
      .append('svg')
      .attr('class', 'd3-overlay')
      .style('position', 'absolute')
      .style('top', '0')
      .style('left', '0')
      .style('pointer-events', 'none')

    // Handle map interactions for D3
    const g = svg.append('g')

    const updateD3Layer = () => {
      const bounds = map.current!.getBounds()
      const topLeft = map.current!.latLngToLayerPoint([bounds.getNorth(), bounds.getWest()])
      const bottomRight = map.current!.latLngToLayerPoint([bounds.getSouth(), bounds.getEast()])

      svg.attr('width', bottomRight.x - topLeft.x + 100).attr('height', bottomRight.y - topLeft.y + 100)

      g.attr('transform', `translate(${-topLeft.x},${-topLeft.y})`)
    }

    map.current.on('zoom', updateD3Layer)
    map.current.on('move', updateD3Layer)
    updateD3Layer()

    return () => {
      svg.remove()
    }
  }, [centerLat, centerLng])

  // Update drone markers
  useEffect(() => {
    if (!map.current) return

    drones.forEach((drone) => {
      let marker = droneMarkersRef.current.get(drone.id)

      if (!marker) {
        const droneIcon = L.divIcon({
          html: `
            <div class="flex items-center justify-center w-8 h-8 bg-blue-500 rounded-full border-2 border-blue-700 text-white text-xs font-bold">
              ${drone.id[0]}
            </div>
          `,
          iconSize: [32, 32],
          className: '',
        })

        marker = L.marker([drone.latitude, drone.longitude], { icon: droneIcon })
          .bindPopup(
            `<div class="font-semibold text-sm">
              <p>Drone: ${drone.id}</p>
              <p>Battery: ${drone.battery}%</p>
              <p>Mission: ${drone.currentMission}</p>
              <p>Altitude: ${drone.altitude}m</p>
            </div>`
          )
          .addTo(map.current!)

        droneMarkersRef.current.set(drone.id, marker)
      } else {
        marker.setLatLng([drone.latitude, drone.longitude])
      }
    })

    // Remove deleted drones
    droneMarkersRef.current.forEach((marker, id) => {
      if (!drones.find((d) => d.id === id)) {
        marker.remove()
        droneMarkersRef.current.delete(id)
      }
    })
  }, [drones])

  // Update survivor markers
  useEffect(() => {
    if (!map.current) return

    survivors.forEach((survivor) => {
      let marker = survivorMarkersRef.current.get(survivor.id)

      if (!marker) {
        const survivorIcon = L.divIcon({
          html: `
            <div class="flex items-center justify-center w-6 h-6 bg-red-500 rounded-full border-2 border-red-700">
              <span class="text-white text-xs">!</span>
            </div>
          `,
          iconSize: [24, 24],
          className: '',
        })

        marker = L.marker([survivor.latitude, survivor.longitude], { icon: survivorIcon })
          .bindPopup(
            `<div class="font-semibold text-sm">
              <p>Survivor: ${survivor.id}</p>
              <p>Probability: ${(survivor.probability * 100).toFixed(1)}%</p>
            </div>`
          )
          .addTo(map.current!)

        survivorMarkersRef.current.set(survivor.id, marker)
      }
    })

    // Remove deleted survivors
    survivorMarkersRef.current.forEach((marker, id) => {
      if (!survivors.find((s) => s.id === id)) {
        marker.remove()
        survivorMarkersRef.current.delete(id)
      }
    })
  }, [survivors])

  return (
    <div className="relative w-full h-full">
      <div ref={mapContainer} className="w-full h-full rounded-lg shadow-lg" />
      <div className="absolute top-4 right-4 bg-white px-4 py-2 rounded-lg shadow-md text-sm z-50">
        <p className="font-semibold text-gray-800">Legend</p>
        <div className="flex items-center gap-2 mt-2">
          <div className="w-4 h-4 bg-blue-500 rounded-full border border-blue-700" />
          <span className="text-xs">Drone</span>
        </div>
        <div className="flex items-center gap-2 mt-1">
          <div className="w-4 h-4 bg-red-500 rounded-full border border-red-700" />
          <span className="text-xs">Survivor</span>
        </div>
      </div>
    </div>
  )
}

export default MapView
