import { useState } from 'react';
import { Card, CardContent, Button, Chip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper, LinearProgress } from '@mui/material';
import { FileText, Download, Eye, PlayCircle, Calculator } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';

interface AssessmentRecord {
  farmId: string;
  farmerName: string;
  municipality: string;
  hectares: number;
  cropStage: string;
  exposurePeriod: string;
  windVelocity: string;
  indemnityFactor: number;
  indemnityAmount: number;
}

export function AssessmentModule() {
  const [isCalculating, setIsCalculating] = useState(false);

  const [assessments] = useState<AssessmentRecord[]>([
    {
      farmId: 'F-001',
      farmerName: 'Juan Dela Cruz',
      municipality: 'Tarlac City',
      hectares: 2.5,
      cropStage: 'Vegetative',
      exposurePeriod: '3 hours - Signal No. 2',
      windVelocity: '61-90 kph',
      indemnityFactor: 0.30,
      indemnityAmount: 22500
    },
    {
      farmId: 'F-002',
      farmerName: 'Maria Santos',
      municipality: 'Tarlac City',
      hectares: 3.2,
      cropStage: 'Reproductive',
      exposurePeriod: '6 hours - Signal No. 3',
      windVelocity: '91-120 kph',
      indemnityFactor: 0.50,
      indemnityAmount: 48000
    },
    {
      farmId: 'F-003',
      farmerName: 'Pedro Reyes',
      municipality: 'Gerona',
      hectares: 1.8,
      cropStage: 'Maturity',
      exposurePeriod: '2 hours - Signal No. 1',
      windVelocity: '30-60 kph',
      indemnityFactor: 0.15,
      indemnityAmount: 8100
    }
  ]);

  const municipalityData = [
    { name: 'Tarlac City', farms: 2, amount: 70500 },
    { name: 'Gerona', farms: 1, amount: 8100 },
    { name: 'Concepcion', farms: 0, amount: 0 },
    { name: 'Victoria', farms: 0, amount: 0 }
  ];

  const cropStageData = [
    { name: 'Vegetative', value: 1, color: '#52b788' },
    { name: 'Reproductive', value: 1, color: '#ffa726' },
    { name: 'Maturity', value: 1, color: '#1e88e5' }
  ];

  const totalIndemnity = assessments.reduce((sum, a) => sum + a.indemnityAmount, 0);
  const avgIndemnityFactor = assessments.reduce((sum, a) => sum + a.indemnityFactor, 0) / assessments.length;

  const handleRunCalculation = () => {
    setIsCalculating(true);
    setTimeout(() => setIsCalculating(false), 3000);
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl" style={{ color: 'var(--primary)' }}>
            Assessment & Reporting Module
          </h2>
          <p className="text-muted-foreground mt-1">
            Automated damage calculation and indemnification report generation
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="contained"
            startIcon={<PlayCircle />}
            onClick={handleRunCalculation}
            disabled={isCalculating}
            sx={{
              bgcolor: 'var(--primary)',
              '&:hover': { bgcolor: 'var(--green-600)' }
            }}
          >
            {isCalculating ? 'Calculating...' : 'Run Automated Calculation'}
          </Button>
          <Button
            variant="outlined"
            startIcon={<Download />}
            sx={{ borderColor: 'var(--border)' }}
          >
            Export CSV Report
          </Button>
        </div>
      </div>

      {isCalculating && (
        <Card sx={{ bgcolor: 'var(--blue-50)' }}>
          <CardContent>
            <div className="flex items-center gap-4">
              <Calculator className="w-8 h-8" style={{ color: 'var(--blue-500)' }} />
              <div className="flex-1">
                <p className="font-medium">Processing automated assessment...</p>
                <p className="text-sm text-muted-foreground">
                  Mapping exposure periods, calculating wind velocity factors, and computing indemnity payments
                </p>
                <LinearProgress sx={{ mt: 2, bgcolor: 'var(--blue-100)', '& .MuiLinearProgress-bar': { bgcolor: 'var(--blue-500)' } }} />
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card sx={{ bgcolor: 'var(--green-50)', borderLeft: '4px solid var(--green-500)' }}>
          <CardContent>
            <p className="text-sm text-muted-foreground">Total Farms Assessed</p>
            <h3 className="text-3xl mt-2" style={{ color: 'var(--green-500)' }}>{assessments.length}</h3>
          </CardContent>
        </Card>

        <Card sx={{ bgcolor: 'var(--blue-50)', borderLeft: '4px solid var(--blue-500)' }}>
          <CardContent>
            <p className="text-sm text-muted-foreground">Total Indemnity (PHP)</p>
            <h3 className="text-2xl mt-2" style={{ color: 'var(--blue-500)' }}>
              ₱{totalIndemnity.toLocaleString()}
            </h3>
          </CardContent>
        </Card>

        <Card sx={{ bgcolor: 'var(--gold-50)', borderLeft: '4px solid var(--gold-500)' }}>
          <CardContent>
            <p className="text-sm text-muted-foreground">Avg Indemnity Factor</p>
            <h3 className="text-3xl mt-2" style={{ color: 'var(--gold-600)' }}>
              {(avgIndemnityFactor * 100).toFixed(0)}%
            </h3>
          </CardContent>
        </Card>

        <Card sx={{ bgcolor: 'var(--muted)', borderLeft: '4px solid var(--foreground)' }}>
          <CardContent>
            <p className="text-sm text-muted-foreground">Total Hectares</p>
            <h3 className="text-3xl mt-2">
              {assessments.reduce((sum, a) => sum + a.hectares, 0)} ha
            </h3>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardContent>
            <h3 className="text-xl mb-4">Indemnity by Municipality</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={municipalityData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="amount" fill="var(--primary)" name="Indemnity Amount (PHP)" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <h3 className="text-xl mb-4">Distribution by Crop Stage</h3>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={cropStageData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={(entry) => entry.name}
                  outerRadius={100}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {cropStageData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xl">Assessment Results ({assessments.length} records)</h3>
            <div className="flex gap-2">
              <Button
                variant="outlined"
                size="small"
                startIcon={<Eye />}
                sx={{ borderColor: 'var(--border)' }}
              >
                Preview Report
              </Button>
              <Button
                variant="contained"
                size="small"
                startIcon={<FileText />}
                sx={{
                  bgcolor: 'var(--accent)',
                  color: 'var(--accent-foreground)',
                  '&:hover': { bgcolor: 'var(--gold-600)' }
                }}
              >
                Generate Report
              </Button>
            </div>
          </div>

          <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 500 }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ bgcolor: 'var(--muted)' }}><strong>Farm ID</strong></TableCell>
                  <TableCell sx={{ bgcolor: 'var(--muted)' }}><strong>Farmer Name</strong></TableCell>
                  <TableCell sx={{ bgcolor: 'var(--muted)' }}><strong>Municipality</strong></TableCell>
                  <TableCell sx={{ bgcolor: 'var(--muted)' }}><strong>Area (ha)</strong></TableCell>
                  <TableCell sx={{ bgcolor: 'var(--muted)' }}><strong>Crop Stage</strong></TableCell>
                  <TableCell sx={{ bgcolor: 'var(--muted)' }}><strong>Exposure Period</strong></TableCell>
                  <TableCell sx={{ bgcolor: 'var(--muted)' }}><strong>Wind Velocity</strong></TableCell>
                  <TableCell sx={{ bgcolor: 'var(--muted)' }}><strong>Factor</strong></TableCell>
                  <TableCell sx={{ bgcolor: 'var(--muted)' }}><strong>Indemnity (PHP)</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {assessments.map((record) => (
                  <TableRow key={record.farmId} hover>
                    <TableCell>{record.farmId}</TableCell>
                    <TableCell>{record.farmerName}</TableCell>
                    <TableCell>{record.municipality}</TableCell>
                    <TableCell>{record.hectares}</TableCell>
                    <TableCell>
                      <Chip
                        label={record.cropStage}
                        size="small"
                        sx={{ fontSize: '0.75rem' }}
                      />
                    </TableCell>
                    <TableCell>{record.exposurePeriod}</TableCell>
                    <TableCell>{record.windVelocity}</TableCell>
                    <TableCell>
                      <Chip
                        label={`${(record.indemnityFactor * 100).toFixed(0)}%`}
                        size="small"
                        sx={{
                          bgcolor: record.indemnityFactor >= 0.4 ? 'var(--destructive)' : 'var(--accent)',
                          color: 'white',
                          fontSize: '0.75rem'
                        }}
                      />
                    </TableCell>
                    <TableCell>
                      <strong style={{ color: 'var(--primary)' }}>
                        ₱{record.indemnityAmount.toLocaleString()}
                      </strong>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <div className="mt-4 p-4 rounded-lg" style={{ backgroundColor: 'var(--muted)' }}>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <p className="text-sm text-muted-foreground">Total Records</p>
                <p className="text-xl font-medium">{assessments.length} farms</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Total Coverage Area</p>
                <p className="text-xl font-medium">
                  {assessments.reduce((sum, a) => sum + a.hectares, 0)} hectares
                </p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Total Indemnity Payment</p>
                <p className="text-xl font-medium" style={{ color: 'var(--primary)' }}>
                  ₱{totalIndemnity.toLocaleString()}
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
