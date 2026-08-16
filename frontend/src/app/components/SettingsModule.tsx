import { useState } from 'react';
import { Card, CardContent, Button, TextField, Select, MenuItem, FormControl, InputLabel, Switch, FormControlLabel, Chip, type SelectChangeEvent } from '@mui/material';
import { Save, RefreshCw, Database, Mail, Lock, User, Settings as SettingsIcon } from 'lucide-react';

export function SettingsModule() {
  const [sessionTimeout, setSessionTimeout] = useState('5');
  const [autoSave, setAutoSave] = useState(true);
  const [emailNotifications, setEmailNotifications] = useState(true);
  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl" style={{ color: 'var(--primary)' }}>
            Calibration & Settings Module
          </h2>
          <p className="text-muted-foreground mt-1">
            System configuration and administrative controls
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outlined"
            startIcon={<RefreshCw />}
            sx={{ borderColor: 'var(--border)' }}
          >
            Reset to Defaults
          </Button>
          <Button
            variant="contained"
            startIcon={<Save />}
            sx={{
              bgcolor: 'var(--primary)',
              '&:hover': { bgcolor: 'var(--green-600)' }
            }}
          >
            Save Changes
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardContent>
            <div className="flex items-center gap-3 mb-4">
              <Database className="w-6 h-6" style={{ color: 'var(--blue-500)' }} />
              <h3 className="text-xl">Database Configuration</h3>
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between p-3 rounded" style={{ backgroundColor: 'var(--muted)' }}>
                <div>
                  <p className="font-medium">PostgreSQL + PostGIS</p>
                  <p className="text-sm text-muted-foreground">Localized spatial database</p>
                </div>
                <Chip
                  label="Active"
                  size="small"
                  sx={{ bgcolor: 'var(--green-500)', color: 'white' }}
                />
              </div>

              <div className="flex items-center justify-between p-3 rounded" style={{ backgroundColor: 'var(--muted)' }}>
                <span>Last Backup</span>
                <span className="text-sm">2 hours ago</span>
              </div>

              <Button
                fullWidth
                variant="outlined"
                startIcon={<Database />}
                sx={{ borderColor: 'var(--blue-500)', color: 'var(--blue-500)' }}
              >
                Execute Manual Backup
              </Button>

              <Button
                fullWidth
                variant="outlined"
                startIcon={<RefreshCw />}
                sx={{ borderColor: 'var(--border)' }}
              >
                View Backup History
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent>
          <div className="flex items-center gap-3 mb-4">
            <SettingsIcon className="w-6 h-6" style={{ color: 'var(--accent)' }} />
            <h3 className="text-xl">System Parameters</h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-4">
              <FormControl fullWidth>
                <InputLabel>Session Timeout (minutes)</InputLabel>
                <Select
                  value={sessionTimeout}
                  label="Session Timeout (minutes)"
                  onChange={(e: SelectChangeEvent) => setSessionTimeout(e.target.value)}
                >
                  <MenuItem value="5">5 minutes</MenuItem>
                  <MenuItem value="10">10 minutes</MenuItem>
                  <MenuItem value="15">15 minutes</MenuItem>
                  <MenuItem value="30">30 minutes</MenuItem>
                  <MenuItem value="60">60 minutes</MenuItem>
                </Select>
              </FormControl>

              <FormControlLabel
                control={
                  <Switch
                    checked={autoSave}
                    onChange={(e) => setAutoSave(e.target.checked)}
                    sx={{
                      '& .MuiSwitch-switchBase.Mui-checked': {
                        color: 'var(--primary)'
                      },
                      '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': {
                        backgroundColor: 'var(--primary)'
                      }
                    }}
                  />
                }
                label="Enable Auto-Save"
              />

              <FormControlLabel
                control={
                  <Switch
                    checked={emailNotifications}
                    onChange={(e) => setEmailNotifications(e.target.checked)}
                    sx={{
                      '& .MuiSwitch-switchBase.Mui-checked': {
                        color: 'var(--primary)'
                      },
                      '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': {
                        backgroundColor: 'var(--primary)'
                      }
                    }}
                  />
                }
                label="Email Notifications"
              />
            </div>

            <div className="space-y-3">
              <div className="p-3 rounded" style={{ backgroundColor: 'var(--muted)' }}>
                <p className="text-sm font-medium mb-2">Wind Velocity Ranges</p>
                <div className="space-y-1 text-sm text-muted-foreground">
                  <p>Signal No. 1: 30-60 kph</p>
                  <p>Signal No. 2: 61-90 kph</p>
                  <p>Signal No. 3: 91-120 kph</p>
                  <p>Signal No. 4: 121-170 kph</p>
                  <p>Signal No. 5: 171+ kph</p>
                </div>
              </div>

              <Button
                fullWidth
                variant="outlined"
                sx={{ borderColor: 'var(--border)' }}
              >
                Modify Calibration Parameters
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <div className="flex items-center gap-3 mb-4">
            <User className="w-6 h-6" style={{ color: 'var(--secondary)' }} />
            <h3 className="text-xl">User Management</h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card variant="outlined">
              <CardContent>
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-12 h-12 rounded-full flex items-center justify-center" style={{ backgroundColor: 'var(--primary)' }}>
                    <User className="w-6 h-6 text-white" />
                  </div>
                  <div>
                    <p className="font-medium">GIS Specialists</p>
                    <p className="text-sm text-muted-foreground">Active users: 5</p>
                  </div>
                </div>
                <Button
                  fullWidth
                  variant="outlined"
                  size="small"
                  sx={{ borderColor: 'var(--border)' }}
                >
                  Manage Users
                </Button>
              </CardContent>
            </Card>

            <Card variant="outlined">
              <CardContent>
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-12 h-12 rounded-full flex items-center justify-center" style={{ backgroundColor: 'var(--secondary)' }}>
                    <Lock className="w-6 h-6 text-white" />
                  </div>
                  <div>
                    <p className="font-medium">Administrators</p>
                    <p className="text-sm text-muted-foreground">Active users: 2</p>
                  </div>
                </div>
                <Button
                  fullWidth
                  variant="outlined"
                  size="small"
                  sx={{ borderColor: 'var(--border)' }}
                >
                  Manage Access
                </Button>
              </CardContent>
            </Card>

            <Card variant="outlined">
              <CardContent>
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-12 h-12 rounded-full flex items-center justify-center" style={{ backgroundColor: 'var(--accent)' }}>
                    <Mail className="w-6 h-6 text-white" />
                  </div>
                  <div>
                    <p className="font-medium">Email Alerts</p>
                    <p className="text-sm text-muted-foreground">Recipients: 8</p>
                  </div>
                </div>
                <Button
                  fullWidth
                  variant="outlined"
                  size="small"
                  sx={{ borderColor: 'var(--border)' }}
                >
                  Configure Alerts
                </Button>
              </CardContent>
            </Card>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <div className="flex items-center gap-3 mb-4">
            <RefreshCw className="w-6 h-6" style={{ color: 'var(--foreground)' }} />
            <h3 className="text-xl">PAGASA Parser Configuration</h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-4">
              <TextField
                fullWidth
                label="PAGASA URL Endpoint"
                defaultValue="https://www.pagasa.dost.gov.ph/tropical-cyclone"
                variant="outlined"
                helperText="Source URL for bulletin downloads"
              />

              <FormControl fullWidth>
                <InputLabel>Parsing Interval</InputLabel>
                <Select defaultValue="3" label="Parsing Interval">
                  <MenuItem value="1">Every 1 hour</MenuItem>
                  <MenuItem value="3">Every 3 hours</MenuItem>
                  <MenuItem value="6">Every 6 hours</MenuItem>
                  <MenuItem value="12">Every 12 hours</MenuItem>
                </Select>
              </FormControl>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 rounded" style={{ backgroundColor: 'var(--muted)' }}>
                <span>Parser Status</span>
                <Chip
                  label="Running"
                  size="small"
                  sx={{ bgcolor: 'var(--green-500)', color: 'white' }}
                />
              </div>

              <div className="flex items-center justify-between p-3 rounded" style={{ backgroundColor: 'var(--muted)' }}>
                <span>Last Parse Attempt</span>
                <span className="text-sm">5 minutes ago</span>
              </div>

              <div className="flex items-center justify-between p-3 rounded" style={{ backgroundColor: 'var(--muted)' }}>
                <span>Total Bulletins Parsed</span>
                <span className="text-sm font-medium">247</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
