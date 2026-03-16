# Drone Orchestration Frontend

A React TypeScript dashboard for real-time drone swarm orchestration and disaster zone monitoring, styled after Palantir's Maven Smart System design.

## Architecture

### Component Structure

```
src/
├── components/
│   ├── MapView.tsx          # Leaflet map with drone/survivor markers & D3 heatmap overlay
│   ├── MissionLog.tsx       # Left sidebar: streaming mission log from backend agent
│   └── DroneStatus.tsx      # Right sidebar: drone fleet status dashboard
├── types/
│   └── index.ts             # TypeScript interfaces for drones, survivors, logs
├── App.tsx                  # Main layout: 3-column dashboard (log, map, status)
├── main.tsx                 # Entry point
└── index.css                # Global styles + Leaflet/D3 customizations
```

## Features

### 🗺️ MapView Component
- **Leaflet.js** integration for 2D disaster zone mapping
- Interactive zoom/pan controls
- **Drone Markers** (blue circles) showing real-time position
- **Survivor Detection Points** (red markers) with probability indicators
- **D3.js Heatmap Overlay** (placeholder for search coverage visualization)
- Custom legend and tooltips

### 📊 MissionLog Component
- Streaming mission logs from backend agent
- Color-coded message types: `info`, `warning`, `success`, `error`
- Auto-scroll to latest entries
- Live indicator showing real-time updates
- Tracks drone ID, timestamp, and reasoning steps

### 🚁 DroneStatus Component
- Grid of drone status cards
- Shows: ID, current status, live mission, battery %, coordinates, altitude
- Battery health visualization with color gradients
- Fleet-wide stats: active drones, average battery
- Real-time updates as drones move

### 🎨 Design
- **Palantir Maven Smart System** aesthetic: dark slate theme, analytical typography
- **Layout**: 25% left sidebar (logs) | 50% center (map) | 25% right sidebar (status)
- **Tailwind CSS** utilities for responsive styling
- Smooth animations and transitions

## Dependencies

```json
{
  "leaflet": "Interactive mapping",
  "react-leaflet": "React bindings for Leaflet",
  "d3": "Data visualization (heatmaps, overlays)",
  "tailwindcss": "Utility CSS framework",
  "@tailwindcss/vite": "Vite plugin for Tailwind"
}
```

## Getting Started

### Install Dependencies
```bash
npm install
```

### Run Development Server
```bash
npm run dev
```
Opens at `http://localhost:5173`

### Build for Production
```bash
npm run build
```

## Integration with Backend

### Expected API Endpoints

The frontend expects a WebSocket connection for real-time updates:

```typescript
// Mock data currently used. Replace with real API calls:
// 1. GET /api/drones - Fetch drone fleet status
// 2. GET /api/survivors - Fetch detected survivor locations
// 3. WebSocket /ws/mission-logs - Stream mission log entries
// 4. GET /api/heatmap - Fetch search coverage heatmap data
```

### Mission Log Format

Each log entry follows this TypeScript interface:

```typescript
interface MissionLogEntry {
  id: string
  timestamp: Date
  droneId: string
  message: string
  type: 'info' | 'warning' | 'success' | 'error'
}
```

Example from agent:
```
"ALPHA-01: Drone A has 20% battery, assigning closer sector"
"BETA-02: High probability survivor detected. Ready for human confirmation."
"GAMMA-03: Battery critical. Initiating emergency return to base."
```

## Customization

### Change Disaster Zone Center
Edit `App.tsx`:
```typescript
<MapView drones={drones} survivors={survivors} 
  centerLat={40.7128}    // Change latitude
  centerLng={-74.006}    // Change longitude
/>
```

### Add D3 Heatmap Overlay
In `MapView.tsx`, the D3 SVG overlay is initialized. Add heatmap rendering:

```typescript
// In updateD3Layer function:
const heatmapData = [...] // Your heatmap intensity data
const colorScale = d3.scaleLinear()
  .domain([0, 1])
  .range(['blue', 'red'])

g.selectAll('.heatmap-cell')
  .data(heatmapData)
  .join('rect')
  .attr('x', d => mapInstance.latLngToLayerPoint([d.lat, d.lng]).x)
  .attr('y', d => mapInstance.latLngToLayerPoint([d.lat, d.lng]).y)
  .style('fill', d => colorScale(d.intensity))
```

### Styling
All components use Tailwind CSS utility classes. Edit colors by modifying:
- `src/index.css` - Global styles
- Component className strings - Inline Tailwind utilities

## Performance Notes

- Drone positions update every **2 seconds**
- Mission logs append every **5 seconds** (simulated)
- Leaflet map efficiently updates only changed markers
- Logs limited to last **50 entries** to prevent memory bloat

## TypeScript Strict Mode

The project runs with `strict: true` in `tsconfig.json`. All components:
- ✅ Have explicit return types (`JSX.Element`)
- ✅ Import React types explicitly
- ✅ Use interface types for props
- ✅ Typed state and event handlers

## Future Enhancements

- [ ] WebSocket integration for live backend data
- [ ] D3 heatmap rendering for search coverage
- [ ] Drone path planning visualization
- [ ] Survivor clustering algorithm visualization
- [ ] Real-time battery/fuel optimization display
- [ ] Mission replay/timeline scrubber
- [ ] Export logs to CSV/PDF
- [ ] Dark mode toggle (currently dark by default)
- [ ] Map drawing tools for mission zones
