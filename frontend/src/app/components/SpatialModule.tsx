import { useState, useRef } from 'react';
import { Card, CardContent, Button, Chip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper } from '@mui/material';
import { Upload, MapPin, Download, FileText, Play } from 'lucide-react';
import { MapContainer, TileLayer, Polygon, Popup, Polyline } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

interface FarmRecord {
  id: string;
  farmerName: string;
  municipality: string;
  barangay: string;
  hectares: number;
  cropStage: string;
  isPlanted: boolean;
  coordinates?: [number, number][];
}

export function SpatialModule() {
  const fileInputCSV = useRef<HTMLInputElement>(null);
  const fileInputGPX = useRef<HTMLInputElement>(null);

  const [farms] = useState<FarmRecord[]>([
    {
      id: 'F-001',
      farmerName: 'Juan Dela Cruz',
      municipality: 'Tarlac City',
      barangay: 'San Vicente',
      hectares: 2.5,
      cropStage: 'Vegetative',
      isPlanted: true,
      coordinates: [[15.4817, 120.5979], [15.4827, 120.5979], [15.4827, 120.5999], [15.4817, 120.5999]]
    },
    {
      id: 'F-002',
      farmerName: 'Maria Santos',
      municipality: 'Tarlac City',
      barangay: 'San Isidro',
      hectares: 3.2,
      cropStage: 'Reproductive',
      isPlanted: true,
      coordinates: [[15.4847, 120.6009], [15.4857, 120.6009], [15.4857, 120.6029], [15.4847, 120.6029]]
    },
    {
      id: 'F-003',
      farmerName: 'Pedro Reyes',
      municipality: 'Gerona',
      barangay: 'Matindeg',
      hectares: 1.8,
      cropStage: 'Maturity',
      isPlanted: true,
      coordinates: [[15.5017, 120.6179], [15.5027, 120.6179], [15.5027, 120.6199], [15.5017, 120.6199]]
    }
  ]);

  const [selectedFarm, setSelectedFarm] = useState<FarmRecord | null>(null);

  const typhoonPath: [number, number][] = [
    [15.4, 120.5],
    [15.45, 120.55],
    [15.5, 120.6],
    [15.55, 120.65]
  ];

  const getCropStageColor = (stage: string) => {
    switch (stage) {
      case 'Vegetative': return '#52b788';
      case 'Reproductive': return '#ffa726';
      case 'Maturity': return '#1e88e5';
      default: return '#666666';
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl" style={{ color: 'var(--primary)' }}>
            Spatial Analysis & Data Import Module
          </h2>
          <p className="text-muted-foreground mt-1">
            Interactive GIS mapping with typhoon trajectory and farm polygons
          </p>
        </div>
        <Button
          variant="contained"
          startIcon={<Play />}
          sx={{
            bgcolor: 'var(--accent)',
            color: 'var(--accent-foreground)',
            '&:hover': { bgcolor: 'var(--gold-600)' }
          }}
        >
          Run Analysis
        </Button>
      </div>

      <Card>
        <CardContent>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xl">Interactive Map View</h3>
            <div className="flex gap-2">
              <Button
                variant="outlined"
                size="small"
                startIcon={<Download />}
                sx={{ borderColor: 'var(--border)' }}
              >
                Export Exposure Report
              </Button>
              <Button
                variant="outlined"
                size="small"
                startIcon={<MapPin />}
                sx={{ borderColor: 'var(--border)' }}
              >
                Map Tools
              </Button>
            </div>
          </div>

          <div className="rounded-lg overflow-hidden border" style={{ borderColor: 'var(--border)', height: '500px' }}>
            <MapContainer
              center={[15.48, 120.60]}
              zoom={12}
              style={{ height: '100%', width: '100%' }}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />

              <Polyline
                positions={typhoonPath}
                pathOptions={{
                  color: '#d32f2f',
                  weight: 4,
                  opacity: 0.8,
                  dashArray: '10, 10'
                }}
              />

              {farms.map((farm) => farm.coordinates ? (
                <Polygon
                  key={farm.id}
                  positions={farm.coordinates}
                  pathOptions={{
                    color: getCropStageColor(farm.cropStage),
                    fillColor: getCropStageColor(farm.cropStage),
                    fillOpacity: 0.4,
                    weight: 2
                  }}
                  eventHandlers={{
                    click: () => setSelectedFarm(farm)
                  }}
                >
                  <Popup>
                    <div className="p-2">
                      <h4 className="font-medium">{farm.farmerName}</h4>
                      <p className="text-sm text-muted-foreground">{farm.id}</p>
                      <div className="mt-2 space-y-1 text-sm">
                        <p><strong>Location:</strong> {farm.barangay}, {farm.municipality}</p>
                        <p><strong>Area:</strong> {farm.hectares} ha</p>
                        <p><strong>Crop Stage:</strong> {farm.cropStage}</p>
                        <p><strong>Status:</strong> {farm.isPlanted ? 'Planted' : 'Not Planted'}</p>
                      </div>
                    </div>
                  </Popup>
                </Polygon>
              ) : null)}
            </MapContainer>
          </div>

          <div className="flex items-center gap-4 mt-4 text-sm">
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 rounded" style={{ backgroundColor: '#52b788' }}></div>
              <span>Vegetative Stage</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 rounded" style={{ backgroundColor: '#ffa726' }}></div>
              <span>Reproductive Stage</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 rounded" style={{ backgroundColor: '#1e88e5' }}></div>
              <span>Maturity Stage</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-4" style={{ borderTop: '3px dashed #d32f2f' }}></div>
              <span>Typhoon Trajectory</span>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardContent>
            <h3 className="text-xl mb-4">Import Farmer Records (CSV)</h3>
            <div
              className="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer hover:bg-muted/50 transition-colors"
              style={{ borderColor: 'var(--border)' }}
              onClick={() => fileInputCSV.current?.click()}
            >
              <Upload className="w-12 h-12 mx-auto mb-4" style={{ color: 'var(--primary)' }} />
              <p className="font-medium mb-2">Drag and drop CSV file here</p>
              <p className="text-sm text-muted-foreground mb-4">or click to browse</p>
              <Button
                variant="outlined"
                sx={{ borderColor: 'var(--primary)', color: 'var(--primary)' }}
              >
                Select CSV File
              </Button>
              <input
                ref={fileInputCSV}
                type="file"
                accept=".csv"
                className="hidden"
              />
            </div>
            <div className="mt-4 text-sm text-muted-foreground">
              <p>Supported format: PCIC CSV format</p>
              <p>Maximum file size: 50 MB</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <h3 className="text-xl mb-4">Upload Farm Polygons (GPX)</h3>
            <div
              className="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer hover:bg-muted/50 transition-colors"
              style={{ borderColor: 'var(--border)' }}
              onClick={() => fileInputGPX.current?.click()}
            >
              <MapPin className="w-12 h-12 mx-auto mb-4" style={{ color: 'var(--secondary)' }} />
              <p className="font-medium mb-2">Drag and drop GPX file here</p>
              <p className="text-sm text-muted-foreground mb-4">or click to browse</p>
              <Button
                variant="outlined"
                sx={{ borderColor: 'var(--secondary)', color: 'var(--secondary)' }}
              >
                Select GPX File
              </Button>
              <input
                ref={fileInputGPX}
                type="file"
                accept=".gpx"
                className="hidden"
              />
            </div>
            <div className="mt-4 text-sm text-muted-foreground">
              <p>Supported format: GPX (GPS Exchange Format)</p>
              <p>Maximum file size: 100 MB</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xl">Imported Farm Records ({farms.length})</h3>
            {selectedFarm && (
              <Chip
                label={`Selected: ${selectedFarm.farmerName}`}
                onDelete={() => setSelectedFarm(null)}
                sx={{ bgcolor: 'var(--primary)', color: 'white' }}
              />
            )}
          </div>

          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow sx={{ bgcolor: 'var(--muted)' }}>
                  <TableCell><strong>Farm ID</strong></TableCell>
                  <TableCell><strong>Farmer Name</strong></TableCell>
                  <TableCell><strong>Municipality</strong></TableCell>
                  <TableCell><strong>Barangay</strong></TableCell>
                  <TableCell><strong>Area (ha)</strong></TableCell>
                  <TableCell><strong>Crop Stage</strong></TableCell>
                  <TableCell><strong>Status</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {farms.map((farm) => (
                  <TableRow
                    key={farm.id}
                    hover
                    onClick={() => setSelectedFarm(farm)}
                    sx={{
                      cursor: 'pointer',
                      bgcolor: selectedFarm?.id === farm.id ? 'var(--green-50)' : 'transparent'
                    }}
                  >
                    <TableCell>{farm.id}</TableCell>
                    <TableCell>{farm.farmerName}</TableCell>
                    <TableCell>{farm.municipality}</TableCell>
                    <TableCell>{farm.barangay}</TableCell>
                    <TableCell>{farm.hectares}</TableCell>
                    <TableCell>
                      <Chip
                        label={farm.cropStage}
                        size="small"
                        sx={{
                          bgcolor: getCropStageColor(farm.cropStage),
                          color: 'white',
                          fontSize: '0.75rem'
                        }}
                      />
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={farm.isPlanted ? 'Planted' : 'Not Planted'}
                        size="small"
                        variant={farm.isPlanted ? 'filled' : 'outlined'}
                        sx={{
                          bgcolor: farm.isPlanted ? 'var(--green-500)' : 'transparent',
                          color: farm.isPlanted ? 'white' : 'var(--foreground)',
                          fontSize: '0.75rem'
                        }}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>
    </div>
  );
}
