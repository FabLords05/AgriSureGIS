import { useState } from 'react';
import { Card, CardContent, Button, Chip, Alert } from '@mui/material';
import { CloudDownload, AlertCircle, CheckCircle, Clock, Download, Bell } from 'lucide-react';

interface TyphoonBulletin {
  id: string;
  name: string;
  timestamp: string;
  signal: string;
  status: 'active' | 'completed';
  downloaded: boolean;
}

export function MonitoringModule() {
  const [bulletins] = useState<TyphoonBulletin[]>([
    {
      id: 'TCB-001',
      name: 'Typhoon AMBO',
      timestamp: '2026-05-23 14:00:00',
      signal: 'Signal No. 3',
      status: 'active',
      downloaded: true
    },
    {
      id: 'TCB-002',
      name: 'Typhoon AMBO',
      timestamp: '2026-05-23 11:00:00',
      signal: 'Signal No. 2',
      status: 'completed',
      downloaded: true
    },
    {
      id: 'TCB-003',
      name: 'Typhoon AMBO',
      timestamp: '2026-05-23 08:00:00',
      signal: 'Signal No. 1',
      status: 'completed',
      downloaded: true
    }
  ]);

  const [latestAlert] = useState({
    message: 'New PAGASA Tropical Cyclone Bulletin detected!',
    timestamp: '2 minutes ago'
  });

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl" style={{ color: 'var(--primary)' }}>
            Monitoring & Extraction Module
          </h2>
          <p className="text-muted-foreground mt-1">
            Real-time PAGASA Tropical Cyclone Bulletin monitoring and extraction
          </p>
        </div>
        <Button
          variant="contained"
          startIcon={<Bell />}
          sx={{
            bgcolor: 'var(--accent)',
            color: 'var(--accent-foreground)',
            '&:hover': { bgcolor: 'var(--gold-600)' }
          }}
        >
          Notification Settings
        </Button>
      </div>

      <Alert
        severity="info"
        icon={<AlertCircle className="w-5 h-5" />}
        sx={{
          bgcolor: 'var(--blue-50)',
          color: 'var(--foreground)',
          '& .MuiAlert-icon': { color: 'var(--blue-500)' }
        }}
      >
        <div className="flex items-center justify-between">
          <div>
            <strong>{latestAlert.message}</strong>
            <p className="text-sm mt-1">Downloaded at {latestAlert.timestamp}</p>
          </div>
          <Button
            size="small"
            variant="outlined"
            sx={{ borderColor: 'var(--blue-500)', color: 'var(--blue-500)' }}
          >
            View Details
          </Button>
        </div>
      </Alert>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card sx={{ bgcolor: 'var(--green-50)', borderLeft: '4px solid var(--green-500)' }}>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Active Typhoons</p>
                <h3 className="text-3xl mt-2" style={{ color: 'var(--green-500)' }}>1</h3>
              </div>
              <CloudDownload className="w-12 h-12" style={{ color: 'var(--green-500)' }} />
            </div>
          </CardContent>
        </Card>

        <Card sx={{ bgcolor: 'var(--blue-50)', borderLeft: '4px solid var(--blue-500)' }}>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Bulletins Downloaded</p>
                <h3 className="text-3xl mt-2" style={{ color: 'var(--blue-500)' }}>12</h3>
              </div>
              <Download className="w-12 h-12" style={{ color: 'var(--blue-500)' }} />
            </div>
          </CardContent>
        </Card>

        <Card sx={{ bgcolor: 'var(--gold-50)', borderLeft: '4px solid var(--gold-500)' }}>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Last Update</p>
                <h3 className="text-lg mt-2" style={{ color: 'var(--gold-600)' }}>2 min ago</h3>
              </div>
              <Clock className="w-12 h-12" style={{ color: 'var(--gold-500)' }} />
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xl">PAGASA Tropical Cyclone Bulletins</h3>
            <Button
              variant="contained"
              startIcon={<CloudDownload />}
              sx={{
                bgcolor: 'var(--primary)',
                '&:hover': { bgcolor: 'var(--green-600)' }
              }}
            >
              Parse Latest Bulletin
            </Button>
          </div>

          <div className="space-y-3">
            {bulletins.map((bulletin) => (
              <div
                key={bulletin.id}
                className="flex items-center justify-between p-4 rounded-lg border"
                style={{ borderColor: 'var(--border)', backgroundColor: 'var(--card)' }}
              >
                <div className="flex items-center gap-4">
                  <div
                    className="w-12 h-12 rounded-full flex items-center justify-center"
                    style={{
                      backgroundColor: bulletin.status === 'active' ? 'var(--green-100)' : 'var(--muted)'
                    }}
                  >
                    {bulletin.status === 'active' ? (
                      <AlertCircle className="w-6 h-6" style={{ color: 'var(--green-500)' }} />
                    ) : (
                      <CheckCircle className="w-6 h-6" style={{ color: 'var(--muted-foreground)' }} />
                    )}
                  </div>

                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="font-medium">{bulletin.name}</h4>
                      <Chip
                        label={bulletin.signal}
                        size="small"
                        sx={{
                          bgcolor: 'var(--accent)',
                          color: 'var(--accent-foreground)',
                          fontSize: '0.75rem'
                        }}
                      />
                      {bulletin.status === 'active' && (
                        <Chip
                          label="ACTIVE"
                          size="small"
                          sx={{
                            bgcolor: 'var(--green-500)',
                            color: 'white',
                            fontSize: '0.75rem'
                          }}
                        />
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground mt-1">
                      {bulletin.id} - {bulletin.timestamp}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {bulletin.downloaded && (
                    <Chip
                      icon={<CheckCircle className="w-4 h-4" />}
                      label="Downloaded"
                      size="small"
                      variant="outlined"
                      sx={{ borderColor: 'var(--green-500)', color: 'var(--green-500)' }}
                    />
                  )}
                  <Button
                    variant="outlined"
                    size="small"
                    startIcon={<Download />}
                    sx={{ borderColor: 'var(--border)' }}
                  >
                    View PDF
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <h3 className="text-xl mb-4">System Status</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="flex items-center justify-between p-3 rounded" style={{ backgroundColor: 'var(--muted)' }}>
              <span>PAGASA Parser Service</span>
              <Chip
                label="Running"
                size="small"
                sx={{ bgcolor: 'var(--green-500)', color: 'white' }}
              />
            </div>
            <div className="flex items-center justify-between p-3 rounded" style={{ backgroundColor: 'var(--muted)' }}>
              <span>Email Notification Service</span>
              <Chip
                label="Active"
                size="small"
                sx={{ bgcolor: 'var(--green-500)', color: 'white' }}
              />
            </div>
            <div className="flex items-center justify-between p-3 rounded" style={{ backgroundColor: 'var(--muted)' }}>
              <span>Database Connection</span>
              <Chip
                label="Connected"
                size="small"
                sx={{ bgcolor: 'var(--green-500)', color: 'white' }}
              />
            </div>
            <div className="flex items-center justify-between p-3 rounded" style={{ backgroundColor: 'var(--muted)' }}>
              <span>Last Sync</span>
              <Chip
                label="2 minutes ago"
                size="small"
                sx={{ bgcolor: 'var(--blue-500)', color: 'white' }}
              />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
