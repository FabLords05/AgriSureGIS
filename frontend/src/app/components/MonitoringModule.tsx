import { useEffect, useState } from 'react';
import { Card, CardContent, Button, Chip, Alert } from '@mui/material';
import { CloudDownload, AlertCircle, Clock, Download, Bell } from 'lucide-react';
import { getBulletins, parseBulletins, type Bulletin } from '@/lib/api';

export function MonitoringModule() {
  const [bulletins, setBulletins] = useState<Bulletin[]>([]);
  const [isLoadingBulletins, setIsLoadingBulletins] = useState(false);
  const [isParsing, setIsParsing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadBulletins = async () => {
    setIsLoadingBulletins(true);
    setLoadError(null);
    try {
      setBulletins(await getBulletins());
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Failed to load bulletins.');
    } finally {
      setIsLoadingBulletins(false);
    }
  };

  useEffect(() => {
    loadBulletins();
  }, []);

  const latestAlert = {
    message: 'New PAGASA Tropical Cyclone Bulletin detected!',
    timestamp: '2 minutes ago'
  };

  const handleParseLatest = async () => {
    setIsParsing(true);
    setLoadError(null);
    try {
      await parseBulletins();
      await loadBulletins();
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Failed to parse latest bulletin.');
    } finally {
      setIsParsing(false);
    }
  };

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
              onClick={handleParseLatest}
              disabled={isParsing}
              sx={{
                bgcolor: 'var(--primary)',
                '&:hover': { bgcolor: 'var(--green-600)' }
              }}
            >
              {isParsing ? 'Parsing...' : 'Parse Latest Bulletin'}
            </Button>
          </div>

          {loadError && (
            <div
              className="mb-4 text-sm p-3 rounded"
              style={{ backgroundColor: 'var(--destructive)', color: 'white' }}
            >
              {loadError}
            </div>
          )}

          {isLoadingBulletins && (
            <p className="text-sm text-muted-foreground mb-3">Loading bulletins...</p>
          )}

          {!isLoadingBulletins && bulletins.length === 0 && !loadError && (
            <p className="text-sm text-muted-foreground mb-3">No bulletins found.</p>
          )}

          <div className="space-y-3">
            {bulletins.map((bulletin) => (
              <div
                key={bulletin.tcb_id}
                className="flex items-center justify-between p-4 rounded-lg border"
                style={{ borderColor: 'var(--border)', backgroundColor: 'var(--card)' }}
              >
                <div className="flex items-center gap-4">
                  <div
                    className="w-12 h-12 rounded-full flex items-center justify-center"
                    style={{ backgroundColor: 'var(--muted)' }}
                  >
                    <AlertCircle className="w-6 h-6" style={{ color: 'var(--muted-foreground)' }} />
                  </div>

                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="font-medium">{bulletin.typhoon_name}</h4>
                      {bulletin.category && (
                        <Chip
                          label={bulletin.category}
                          size="small"
                          sx={{
                            bgcolor: 'var(--accent)',
                            color: 'var(--accent-foreground)',
                            fontSize: '0.75rem'
                          }}
                        />
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground mt-1">
                      TCB-{bulletin.tcb_id} (Bulletin #{bulletin.bulletin_count}) - {bulletin.issued_at ?? 'Unknown time'}
                    </p>
                  </div>
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
